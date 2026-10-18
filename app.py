import json
import os
import time
import uuid
import secrets
import hashlib
import threading
import tempfile
import shutil
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, render_template_string, session, redirect, url_for, abort
from werkzeug.utils import secure_filename

# ============ 安全配置 ============
# 管理员账号从环境变量读取，部署前必须设置 LOTTERY_ADMIN_PASSWORD
ADMIN_USERNAME = os.environ.get('LOTTERY_ADMIN_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('LOTTERY_ADMIN_PASSWORD', '')
if not ADMIN_PASSWORD:
    raise RuntimeError('请设置环境变量 LOTTERY_ADMIN_PASSWORD')

# 专属前台管理员（漫展现场工作人员使用，COS名+微信号，可无限次抽奖）
# 用这套信息在前台登记后，不受IP限制、不限抽奖次数、不写入普通参与记录
# 可随时修改为实际使用的COS名+微信号组合
SUPER_COS_NAME = '管理员'
SUPER_WECHAT_ID = 'admin2026'

# 频率限制配置
RATE_LIMIT_GENERAL = 120   # 普通接口：每分钟最多120次
RATE_LIMIT_LOTTERY = 30    # 抽奖接口：每分钟最多30次
RATE_LIMIT_DAILY_PER_IP = 999  # 同一IP每天抽奖次数大幅放宽

# 上传安全配置
ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'}
MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25MB（手机现场原图较大，放宽限制）
MAX_PHOTOS_PER_RECORD = 9  # 每条记录最多上传9张照片（用户要求限制张数，九宫格）

# ============ 应用初始化 ============
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE
app.secret_key = secrets.token_hex(32)  # 每次启动随机生成Session密钥
app.permanent_session_lifetime = timedelta(hours=8)  # 管理员登录8小时过期

DATA_FILE = os.path.join(BASE_DIR, 'data', 'records.json')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'data', 'photos')
CONFIG_FILE = os.path.join(BASE_DIR, 'data', 'config.json')
QR_FOLDER = os.path.join(BASE_DIR, 'data', 'qrcodes')

# 内存频率限制存储（重启清零，生产可换Redis）
rate_store = {}  # { ip: {endpoint: [(timestamp, ...), ...]} }
daily_lottery_store = {}  # { ip: {date: count} }

# ====== 数据文件读写并发锁：线程锁 + 原子写（防并发覆盖） ======
_RECORDS_LOCK = threading.RLock()
_FILE_LOCK_PATH = os.path.join(BASE_DIR, 'data', '.records.lock')


def _posix_file_lock(lock_path, exclusive=True, timeout=10.0):
    """POSIX fcntl 文件锁（跨进程互斥）；Windows 下退化为无锁。
    返回一个可调用的 release 闭包。"""
    lock_fd = None
    try:
        import fcntl as _fcntl
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        end = time.time() + timeout
        flags = _fcntl.LOCK_EX if exclusive else _fcntl.LOCK_SH
        while True:
            try:
                _fcntl.flock(lock_fd, flags | _fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.time() > end:
                    try:
                        os.close(lock_fd)
                    except Exception:
                        pass
                    raise TimeoutError(f"等待 records 文件锁超时 ({timeout}s)")
                time.sleep(0.05)
        def _release():
            try:
                _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
            finally:
                try:
                    os.close(lock_fd)
                except Exception:
                    pass
        return _release
    except ImportError:
        # 非 POSIX 环境（Windows）无跨进程锁，仅靠线程锁
        return lambda: None
    except Exception:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except Exception:
                pass
        return lambda: None


def init_data():
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(QR_FOLDER, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'qq_code': None, 'wechat_code': None, 'qq_number': '', 'wechat_id': ''}, f, ensure_ascii=False)


def load_config():
    """加载站点配置（QR码、联系方式等）"""
    init_data()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'qq_code': None, 'wechat_code': None, 'qq_number': '', 'wechat_id': ''}


def save_config(cfg):
    """保存站点配置"""
    init_data()
    tmp_path = CONFIG_FILE + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, CONFIG_FILE)


def load_records(_acquire_lock=True):
    init_data()
    if _acquire_lock:
        _RECORDS_LOCK.acquire()
        _release_file = None
        try:
            _release_file = _posix_file_lock(_FILE_LOCK_PATH, exclusive=False, timeout=10.0)
        except Exception:
            _release_file = None
        try:
            return load_records(_acquire_lock=False)
        finally:
            try:
                if _release_file is not None:
                    _release_file()
            finally:
                _RECORDS_LOCK.release()
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            records = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 文件损坏时尝试恢复：读备份（如果有）
        backup_path = DATA_FILE + '.bak'
        try:
            if os.path.exists(backup_path):
                with open(backup_path, 'r', encoding='utf-8') as f:
                    records = json.load(f)
            else:
                records = []
        except Exception:
            records = []
    # ========== 数据结构迁移：单张photoUrl→多张photos数组 ==========
    # 老数据结构：{photoUrl, photoUploaded}
    # 新数据结构：{photos: [{id, photoUrl, photoPosition, publicApproved,
    #                         publicApprovedAt, uploadedAt}], photoCount: N}
    need_save = False
    for r in records:
        if 'photos' not in r or not isinstance(r.get('photos'), list):
            photos = []
            old_url = r.get('photoUrl')
            if old_url and r.get('photoUploaded'):
                # 老的单张图→作为第1张（position=1），默认未同意公开
                photos.append({
                    'id': 1,
                    'photoUrl': old_url,
                    'photoPosition': 1,
                    'publicApproved': False,
                    'publicApprovedAt': None,
                    'uploadedAt': r.get('timeStr') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })
            r['photos'] = photos
            r['photoCount'] = len(photos)
            r['photoUploaded'] = len(photos) > 0
            r['photoUrl'] = photos[0]['photoUrl'] if photos else None
            need_save = True
        else:
            # 已有photos字段，补全缺省字段（兼容中间版本）
            max_id = 0
            for p in r['photos']:
                if 'id' not in p:
                    p['id'] = max(1, max_id + 1)
                    need_save = True
                if p['id'] > max_id:
                    max_id = p['id']
                if 'photoPosition' not in p:
                    p['photoPosition'] = p['id']
                    need_save = True
                if 'publicApproved' not in p:
                    p['publicApproved'] = False
                    need_save = True
                if 'publicApprovedAt' not in p:
                    p['publicApprovedAt'] = None
                    need_save = True
                if 'uploadedAt' not in p:
                    p['uploadedAt'] = r.get('timeStr') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    need_save = True
            # 按 photoPosition 升序重排，保证稳定
            if len(r['photos']) > 1:
                sorted_photos = sorted(r['photos'], key=lambda x: (x.get('photoPosition', 999), x.get('id', 0)))
                if [p['id'] for p in sorted_photos] != [p['id'] for p in r['photos']]:
                    r['photos'] = sorted_photos
                    need_save = True
            # 同步 photoCount / photoUrl / photoUploaded 快捷字段
            count = len(r['photos'])
            if r.get('photoCount') != count:
                r['photoCount'] = count
                need_save = True
            uploaded_flag = count > 0
            if r.get('photoUploaded') != uploaded_flag:
                r['photoUploaded'] = uploaded_flag
                need_save = True
            first_url = r['photos'][0]['photoUrl'] if count > 0 else None
            if r.get('photoUrl') != first_url:
                r['photoUrl'] = first_url
                need_save = True
        # 迁移 3：messages 字段（给摄影师留言板，用户上传完照片后可以提修图需求）
        if 'messages' not in r or not isinstance(r.get('messages'), list):
            r['messages'] = []
            need_save = True
        else:
            # 已有 messages：给每条补齐缺省字段
            changed_any = False
            for i, m in enumerate(r['messages']):
                if not isinstance(m, dict):
                    r['messages'][i] = {
                        'id': (i + 1),
                        'createdAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'by': 'user',
                        'cosName': r.get('cosName', ''),
                        'text': str(m) if m is not None else ''
                    }
                    changed_any = True
                    continue
                if 'id' not in m:
                    m['id'] = (i + 1); changed_any = True
                if 'createdAt' not in m:
                    m['createdAt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S'); changed_any = True
                if 'by' not in m:
                    m['by'] = 'user'; changed_any = True
                if 'cosName' not in m:
                    m['cosName'] = r.get('cosName', ''); changed_any = True
                if 'text' not in m:
                    m['text'] = ''; changed_any = True
            if changed_any:
                need_save = True
    if need_save:
        try:
            save_records(records, _acquire_lock=False)
        except Exception:
            pass
    return records


def save_records(records, _acquire_lock=True):
    init_data()
    if _acquire_lock:
        _RECORDS_LOCK.acquire()
        _release_file = None
        try:
            _release_file = _posix_file_lock(_FILE_LOCK_PATH, exclusive=True, timeout=10.0)
        except Exception:
            _release_file = None
        try:
            save_records(records, _acquire_lock=False)
        finally:
            try:
                if _release_file is not None:
                    _release_file()
            finally:
                _RECORDS_LOCK.release()
        return

    data_dir = os.path.dirname(DATA_FILE)
    backup_path = DATA_FILE + '.bak'

    # 原子写：先写临时文件，fsync 后再重命名覆盖，最后再写备份
    fd_tmp, tmp_path = tempfile.mkstemp(prefix='.records_', suffix='.tmp', dir=data_dir)
    try:
        with os.fdopen(fd_tmp, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        # 临时文件→重命名覆盖主文件（POSIX/Windows 下 rename 只要目标存在且用户有权限都是原子级）
        try:
            os.replace(tmp_path, DATA_FILE)
        except OSError:
            # 极端情况：os.replace 在某些 Windows 卷上失败；退化为 shutil.move
            shutil.move(tmp_path, DATA_FILE)
        # 再写一份备份（非原子，但至少有一份最新）
        try:
            shutil.copy2(DATA_FILE, backup_path)
        except Exception:
            pass
    finally:
        # 如果临时文件没被重命名，清理它
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ============ 安全工具函数 ============

def get_client_ip():
    """获取真实客户端IP（兼容代理）"""
    xff = request.headers.get('X-Forwarded-For')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def is_super_user(cos_name, wechat_id):
    """判断是否为专属前台管理员（可无限次抽奖）"""
    if not cos_name or not wechat_id:
        return False
    return (
        cos_name.strip() == SUPER_COS_NAME
        and wechat_id.strip() == SUPER_WECHAT_ID
    )


def rate_limit(max_per_minute, endpoint_key=None):
    """频率限制装饰器（专属前台管理员豁免）"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # 尝试从请求体判断是否是专属前台管理员，是则跳过频率限制
            super_bypass = False
            try:
                if request.method == 'POST' and request.is_json:
                    body = request.get_json(silent=True) or {}
                    if is_super_user(body.get('cosName'), body.get('wechatId')):
                        super_bypass = True
            except Exception:
                pass

            if super_bypass:
                return f(*args, **kwargs)

            ip = get_client_ip()
            key = endpoint_key or request.endpoint
            now = time.time()
            window_start = now - 60  # 60秒窗口

            store_key = f"{ip}:{key}"
            if store_key not in rate_store:
                rate_store[store_key] = []
            # 清理过期记录
            rate_store[store_key] = [t for t in rate_store[store_key] if t > window_start]
            # 检查是否超限
            if len(rate_store[store_key]) >= max_per_minute:
                return jsonify({'success': False, 'message': '请求过于频繁，请稍后再试'}), 429
            rate_store[store_key].append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def check_daily_lottery_limit(cos_name=None, wechat_id=None):
    """检查同一IP每日抽奖次数限制（专属前台管理员豁免）"""
    if is_super_user(cos_name, wechat_id):
        return True, None
    ip = get_client_ip()
    today = datetime.now().strftime('%Y-%m-%d')
    if ip not in daily_lottery_store:
        daily_lottery_store[ip] = {}
    if today not in daily_lottery_store[ip]:
        daily_lottery_store[ip][today] = 0
    if daily_lottery_store[ip][today] >= RATE_LIMIT_DAILY_PER_IP:
        return False, f'同一IP每天最多只能抽{RATE_LIMIT_DAILY_PER_IP}次奖'
    daily_lottery_store[ip][today] += 1
    # 清理昨天之前的数据
    for k_ip in list(daily_lottery_store.keys()):
        for k_date in list(daily_lottery_store[k_ip].keys()):
            if k_date != today:
                del daily_lottery_store[k_ip][k_date]
    return True, None


# ============ 50人抽奖池机制 ============
# 总共50个抽奖名额：1个一等奖(20元红包) + 10个二等奖(霞蝶手办) + 39个谢谢参与
# 每次抽奖从池中随机弹出一个，抽完即止；由服务端决定结果，前端传入的 prizeLevel 一律忽略（防作弊）
LOTTERY_POOL_FILE = os.path.join(BASE_DIR, 'data', 'lottery_pool.json')
LOTTERY_TOTAL = 50
LOTTERY_FIRST_COUNT = 1
LOTTERY_SECOND_COUNT = 10
LOTTERY_THANKS_COUNT = LOTTERY_TOTAL - LOTTERY_FIRST_COUNT - LOTTERY_SECOND_COUNT  # 39

PRIZE_NAMES = {1: '20元现金红包', 2: '霞蝶手办', 0: '谢谢参与'}

_POOL_LOCK = threading.RLock()  # 保护池文件的读-改-写，避免并发重复发奖


def init_lottery_pool():
    """初始化抽奖池（仅在文件不存在时创建）"""
    if os.path.exists(LOTTERY_POOL_FILE):
        return
    pool = [1] * LOTTERY_FIRST_COUNT + [2] * LOTTERY_SECOND_COUNT + [0] * LOTTERY_THANKS_COUNT
    secrets.SystemRandom().shuffle(pool)
    data = {'pool': pool, 'total': LOTTERY_TOTAL, 'drawn': 0, 'createdAt': datetime.now().isoformat()}
    with open(LOTTERY_POOL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def draw_from_pool():
    """从抽奖池中随机抽取一个奖品，返回(prize_level, prize_name)。池空则谢谢参与。"""
    with _POOL_LOCK:
        init_lottery_pool()
        try:
            with open(LOTTERY_POOL_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
        pool = data.get('pool', [])
        if not pool:
            return 0, PRIZE_NAMES[0]
        idx = secrets.randbelow(len(pool))
        prize_level = pool.pop(idx)
        data['pool'] = pool
        data['drawn'] = data.get('drawn', 0) + 1
        data['lastDrawnAt'] = datetime.now().isoformat()
        with open(LOTTERY_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        return prize_level, PRIZE_NAMES.get(prize_level, PRIZE_NAMES[0])


def get_pool_status():
    """获取抽奖池当前状态"""
    with _POOL_LOCK:
        init_lottery_pool()
        try:
            with open(LOTTERY_POOL_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
        pool = data.get('pool', [])
        return {
            'total': data.get('total', LOTTERY_TOTAL),
            'drawn': data.get('drawn', 0),
            'remaining': len(pool),
            'firstRemaining': sum(1 for p in pool if p == 1),
            'secondRemaining': sum(1 for p in pool if p == 2),
            'thanksRemaining': sum(1 for p in pool if p == 0),
        }


def reset_lottery_pool():
    """重置抽奖池（后台一键重置时调用）"""
    with _POOL_LOCK:
        if os.path.exists(LOTTERY_POOL_FILE):
            os.remove(LOTTERY_POOL_FILE)
        init_lottery_pool()


def admin_required(f):
    """管理员登录认证装饰器"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged_in'):
            # API请求返回401，页面请求跳登录页
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': '未登录，请先登录管理员账号'}), 401
            return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return wrapper


def verify_file_is_image(file_storage):
    """严格校验文件是不是真图片（不信后缀和Content-Type）"""
    try:
        # 方法1：读文件头魔数
        file_storage.seek(0)
        header = file_storage.read(12)  # 读前12字节足够判断魔数
        file_storage.seek(0)  # 复位，方便后续读取

        # JPEG: FF D8 FF
        if header[:3] == b'\xff\xd8\xff':
            return True, 'jpg'
        # PNG: 89 50 4E 47 0D 0A 1A 0A
        if header[:8] == b'\x89PNG\r\n\x1a\n':
            return True, 'png'
        # GIF87a / GIF89a
        if header[:6] in (b'GIF87a', b'GIF89a'):
            return True, 'gif'
        # WebP: RIFF....WEBP
        if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
            return True, 'webp'
        # HEIC/HEIF (iPhone 默认拍照格式): ftyp box + brand heic/heix/hevc/hevx/mif1/msf1
        if header[4:8] == b'ftyp' and header[8:12] in (b'heic', b'heix', b'hevc', b'hevx', b'mif1', b'msf1', b'hevm'):
            return True, 'heic'

        return False, None
    except:
        return False, None


def safe_rewrite_image(src_stream, ext):
    """用Pillow重新编码图片，彻底销毁木马字节。返回(新文件字节, 新扩展名)。
    
    关键修复：
    - 手机拍摄照片 Exif Orientation 自动转正（ImageOps.exif_transpose）
    - RGBA/LA/P（带透明通道的 PNG/GIF）先合成白底再转 JPG，
      避免透明像素被压成纯黑 → 缩略图全黑
    - 最长边 ≥ 2560px 时等比缩小，兼顾清晰度和体积
    - JPG progressive + quality=85，体积/质量最佳平衡点
    """
    try:
        from PIL import Image, ImageOps
        import io
        # 注册 HEIC/HEIF 支持（iPhone 拍照默认格式）
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        img = Image.open(src_stream)
        img.verify()  # 验证完整性
        src_stream.seek(0)
        img = Image.open(src_stream)  # verify后要重新open

        # 1) 手机 Exif 旋转自动转正（避免 orientation=6/3 时方向颠倒显示不对）
        try:
            img = ImageOps.exif_transpose(img)
        except:
            pass

        final_ext = ext
        needs_rgb_white_bg = False
        is_transparent_mode = img.mode in ('RGBA', 'LA', 'P', 'PA')

        if is_transparent_mode:
            # 2) 带透明通道的 PNG/GIF/P → 合成白底再存 JPG，避免透明变纯黑
            img_rgba = img.convert('RGBA')
            white_bg = Image.new('RGBA', img_rgba.size, (255, 255, 255, 255))
            try:
                composite = Image.alpha_composite(white_bg, img_rgba)
            except:
                composite = white_bg.copy()
                composite.paste(img_rgba, mask=img_rgba.split()[-1] if img_rgba.mode == 'RGBA' else None)
            img = composite.convert('RGB')
            final_ext = 'jpg'
            needs_rgb_white_bg = True
        elif img.mode != 'RGB':
            img = img.convert('RGB')
            final_ext = 'jpg'

        # 3) 尺寸限制：最长边 > 2560 → 按比例缩（保留清晰、避免上传 8K 手机原图超大）
        MAX_SIDE = 2560
        w, h = img.size
        if max(w, h) > MAX_SIDE:
            ratio = MAX_SIDE / float(max(w, h))
            new_w = max(1, int(round(w * ratio)))
            new_h = max(1, int(round(h * ratio)))
            try:
                img = img.resize((new_w, new_h), Image.LANCZOS)
            except Exception:
                try:
                    img = img.resize((new_w, new_h), Image.BILINEAR)
                except Exception:
                    pass

        # 4) 根据格式重新编码
        out = io.BytesIO()
        code_ext = final_ext if final_ext in ('jpg', 'png', 'gif') else 'jpg'

        if code_ext == 'jpg':
            img.save(out, format='JPEG', quality=85, optimize=True, progressive=True)
            final_ext = 'jpg'
        elif code_ext == 'png':
            img.save(out, format='PNG', optimize=True)
            final_ext = 'png'
        elif code_ext == 'gif':
            img.save(out, format='GIF')
            final_ext = 'gif'
        else:
            img.save(out, format='JPEG', quality=85, optimize=True, progressive=True)
            final_ext = 'jpg'

        out.seek(0)
        return True, out.read(), final_ext
    except Exception as e:
        # 没有Pillow或者处理失败，就只返回原始字节（至少过了魔数校验）
        try:
            src_stream.seek(0)
            return False, src_stream.read(), ext
        except:
            return False, None, ext


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


# 允许访问的白名单静态文件（防止目录穿越到data等敏感目录）
_SAFE_STATIC_PREFIXES = ('css/', 'js/', 'images/', 'fonts/', 'audio/')
_SAFE_STATIC_FILES = ('index.html', 'favicon.ico', 'robots.txt')

@app.route('/<path:path>')
def static_files(path):
    # 禁止直接访问data目录（防止下载记录、直接访问未授权图片）
    if path.startswith('data/') and not path.startswith('data/photos/'):
        abort(403)
    # 白名单目录 + 根目录安全文件
    safe = (
        any(path.startswith(p) for p in _SAFE_STATIC_PREFIXES)
        or path in _SAFE_STATIC_FILES
    )
    # 后台页面也放行（/admin, /admin/dashboard会被下面的路由覆盖；/admin开头的静态资源不经过这里）
    if path.startswith('admin'):
        return send_from_directory('.', path)
    if not safe:
        abort(404)
    return send_from_directory('.', path)


# ============ 管理员登录相关 ============

ADMIN_LOGIN_HTML = r'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>管理员登录 · 漫展抽奖控制台</title>
<link rel="stylesheet" href="/css/admin.css?v=m3">
<style>
  /* 登录页专属：双栏玻璃布局 —— 青白风统一版 */
  body { display: flex; align-items: center; justify-content: center; padding: 40px 24px;
         background:
           radial-gradient(circle at 15% 20%, #dbeafe 0%, transparent 55%),
           radial-gradient(circle at 85% 80%, #cffafe 0%, transparent 55%),
           #f0f9ff; }
  .login-shell {
    width: 100%;
    max-width: 960px;
    display: grid;
    grid-template-columns: 1.1fr 1fr;
    border-radius: 32px;
    overflow: hidden;
    box-shadow: 0 30px 80px rgba(14, 165, 233, 0.15), 0 0 0 1px rgba(14, 165, 233, 0.12);
    background: linear-gradient(145deg, #ffffff, #f0f9ff);
    backdrop-filter: blur(28px) saturate(160%);
    -webkit-backdrop-filter: blur(28px) saturate(160%);
    border: 1px solid #bae6fd;
    min-height: 560px;
    position: relative;
  }
  /* 双栏分隔玻璃高光线 */
  .login-shell::after {
    content: '';
    position: absolute;
    top: 8%; bottom: 8%;
    left: 52%;
    width: 1px;
    background: linear-gradient(to bottom, transparent, #7dd3fc, transparent);
    pointer-events: none;
  }
  .login-left {
    padding: 48px 44px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    position: relative;
    overflow: hidden;
  }
  .login-left::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at 20% 20%, rgba(14,165,233,0.14), transparent 45%),
      radial-gradient(circle at 80% 80%, rgba(16,185,129,0.12), transparent 45%);
    pointer-events: none;
  }
  .brand-badge {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 8px 14px;
    border-radius: 999px;
    background: #e0f2fe;
    border: 1px solid #7dd3fc;
    color: #0369a1;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    width: fit-content;
  }
  .brand-badge .bb-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: #0ea5e9;
    box-shadow: 0 0 8px rgba(14,165,233,0.6);
  }
  .brand-big-title {
    font-size: 40px;
    font-weight: 800;
    color: #0c4a6e;
    line-height: 1.2;
    margin-top: 32px;
    letter-spacing: 2px;
  }
  .brand-big-title em {
    font-style: normal;
    background: linear-gradient(135deg, #0ea5e9, #10b981);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .brand-desc {
    color: #475569;
    font-size: 14px;
    margin-top: 14px;
    line-height: 1.7;
  }
  /* 浮动装饰小卡 */
  .decor-cards {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
    margin-top: 36px;
    position: relative;
    z-index: 1;
  }
  .decor-card {
    padding: 14px 16px;
    border-radius: 16px;
    background: #ffffff;
    border: 1px solid #bae6fd;
    box-shadow: 0 4px 16px rgba(14,165,233,0.06);
  }
  .decor-card .dc-num {
    font-size: 22px;
    font-weight: 700;
    color: #0c4a6e;
    margin-bottom: 4px;
  }
  .decor-card.cyan   .dc-num { color: #0284c7; }
  .decor-card.gold   .dc-num { color: #d97706; }
  .decor-card.green  .dc-num { color: #059669; }
  .decor-card.purple .dc-num { color: #7c3aed; }
  .decor-card .dc-label {
    font-size: 11px;
    color: #64748B;
    letter-spacing: 0.5px;
  }
  .login-footer {
    font-size: 11px;
    color: #64748B;
    letter-spacing: 0.5px;
  }

  /* 右栏：登录框 */
  .login-right {
    padding: 48px 44px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  .login-right h2 {
    font-size: 26px;
    color: #0c4a6e;
    font-weight: 700;
    margin-bottom: 6px;
  }
  .login-right .sub {
    font-size: 13px;
    color: #64748B;
    margin-bottom: 32px;
  }
  .form-field { margin-bottom: 20px; }
  .form-field label {
    display: block;
    color: #0369a1;
    font-size: 13px;
    margin-bottom: 8px;
    font-weight: 500;
  }
  .form-field .input-box {
    position: relative;
  }
  .form-field .input-box input {
    width: 100%;
    padding: 14px 16px 14px 46px;
    background: #ffffff;
    border: 1px solid #bae6fd;
    border-radius: 16px;
    color: #0c4a6e;
    font-size: 14px;
    font-family: inherit;
    outline: none;
    transition: all 0.25s ease;
  }
  .form-field .input-box input:focus {
    border-color: #0ea5e9;
    background: #f0f9ff;
    box-shadow: 0 0 0 4px rgba(14,165,233,0.12);
  }
  .form-field .input-box .ico {
    position: absolute;
    left: 16px;
    top: 50%;
    transform: translateY(-50%);
    color: #64748B;
    font-size: 16px;
    pointer-events: none;
  }
  .form-field .input-box input:focus ~ .ico { color: #0ea5e9; }
  .error-box {
    padding: 12px 16px;
    border-radius: 14px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #b91c1c;
    font-size: 13px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .submit-btn {
    width: 100%;
    padding: 15px 20px;
    border-radius: 16px;
    border: none;
    cursor: pointer;
    background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 50%, #10b981 100%);
    background-size: 200% 200%;
    color: #fff;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 2px;
    font-family: inherit;
    transition: all 0.3s ease;
    box-shadow: 0 10px 28px rgba(14,165,233,0.22);
    margin-top: 8px;
  }
  .submit-btn:hover {
    background-position: 100% 100%;
    transform: translateY(-2px);
    box-shadow: 0 14px 34px rgba(16, 185, 129, 0.25);
  }
  .login-right-tip {
    margin-top: 22px;
    text-align: center;
    font-size: 12px;
    color: #64748B;
    letter-spacing: 0.5px;
  }
  @media (max-width: 820px) {
    .login-shell { grid-template-columns: 1fr; }
    .login-shell::after { display: none; }
    .login-left { padding: 36px 28px 12px; }
    .login-right { padding: 12px 28px 36px; }
    .brand-big-title { font-size: 30px; }
    .decor-cards { grid-template-columns: repeat(4, 1fr); }
  }
  @media (max-width: 520px) {
    .decor-cards { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>
  <div class="login-shell">
    <!-- 左栏：品牌 + 装饰 -->
    <div class="login-left">
      <div>
        <div class="brand-badge"><span class="bb-dot"></span>LIVE · 漫展抽奖控制台</div>
        <h1 class="brand-big-title">让每一次抽奖，<br>都成为<em>高光时刻</em>✨</h1>
        <p class="brand-desc">为线下漫展活动打造的沉浸式抽奖体验系统：<br>实时记录、照片分享、数据看板，全流程可视化。</p>
        <div class="decor-cards">
          <div class="decor-card cyan">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
              <div class="dc-num" style="font-size:20px;">👥</div>
              <span style="font-size:9px;padding:2px 7px;border-radius:999px;background:#e0f2fe;color:#0369a1;border:1px solid #7dd3fc;font-weight:600;">LIVE</span>
            </div>
            <div class="dc-num cyan" style="font-size:26px;">128</div>
            <div class="dc-label">累计参与</div>
            <div style="margin-top:10px;height:3px;border-radius:999px;background:#e0f2fe;overflow:hidden;">
              <div style="width:72%;height:100%;background:linear-gradient(90deg,#0ea5e9,#10b981);"></div>
            </div>
          </div>
          <div class="decor-card gold">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
              <div class="dc-num" style="font-size:20px;">🏆</div>
              <span style="font-size:9px;padding:2px 7px;border-radius:999px;background:#fef3c7;color:#92400e;border:1px solid #fcd34d;font-weight:600;">限量10</span>
            </div>
            <div class="dc-num gold" style="font-size:26px;">3<span style="font-size:13px;color:#64748B;font-weight:500;"> /10</span></div>
            <div class="dc-label">一等奖剩余</div>
            <div style="margin-top:10px;height:3px;border-radius:999px;background:#e0f2fe;overflow:hidden;">
              <div style="width:30%;height:100%;background:linear-gradient(90deg,#f59e0b,#d97706);"></div>
            </div>
          </div>
          <div class="decor-card green">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
              <div class="dc-num" style="font-size:20px;">📸</div>
              <span style="font-size:9px;padding:2px 7px;border-radius:999px;background:#d1fae5;color:#065f46;border:1px solid #6ee7b7;font-weight:600;">归档</span>
            </div>
            <div class="dc-num green" style="font-size:26px;">45%</div>
            <div class="dc-label">照片上传率</div>
            <div style="margin-top:10px;height:3px;border-radius:999px;background:#e0f2fe;overflow:hidden;">
              <div style="width:45%;height:100%;background:linear-gradient(90deg,#10b981,#0ea5e9);"></div>
            </div>
          </div>
          <div class="decor-card purple">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
              <div class="dc-num" style="font-size:20px;">📊</div>
              <span style="font-size:9px;padding:2px 7px;border-radius:999px;background:#ede9fe;color:#5b21b6;border:1px solid #c4b5fd;font-weight:600;">实时</span>
            </div>
            <div class="dc-num purple" style="font-size:26px;">ONLINE</div>
            <div class="dc-label">控制台状态</div>
            <div style="margin-top:10px;height:3px;border-radius:999px;background:#e0f2fe;overflow:hidden;">
              <div style="width:100%;height:100%;background:linear-gradient(90deg,#8b5cf6,#6366f1);"></div>
            </div>
          </div>
        </div>
      </div>
      <div class="login-footer">© Cosplay Lottery Console · Designed for Events</div>
    </div>

    <!-- 右栏：表单 -->
    <div class="login-right">
      <h2>管理员登录</h2>
      <p class="sub">请输入管理员账号以进入后台管理</p>
      {% if error %}<div class="error-box">⛔ {{ error }}</div>{% endif %}
      <form method="post" action="{{ url_for('admin_login_page') }}" autocomplete="on">
        <div class="form-field">
          <label>用户名</label>
          <div class="input-box">
            <input type="text" name="username" required autocomplete="username" placeholder="请输入用户名" autofocus>
            <span class="ico">👤</span>
          </div>
        </div>
        <div class="form-field">
          <label>密码</label>
          <div class="input-box">
            <input type="password" name="password" required autocomplete="current-password" placeholder="请输入密码">
            <span class="ico">🔐</span>
          </div>
        </div>
        <button class="submit-btn" type="submit">登 录 系 统</button>
      </form>
      <p class="login-right-tip">🔒 所有操作均有日志记录 · 仅限授权管理员使用</p>
    </div>
  </div>
</body>
</html>
'''


@app.route('/admin/login', methods=['GET', 'POST'])
@rate_limit(10, 'admin_login')  # 登录接口更严：每分钟最多10次（防爆破）
def admin_login_page():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        # 用恒定时间比较，防时序攻击
        user_ok = secrets.compare_digest(username, ADMIN_USERNAME)
        pwd_ok = secrets.compare_digest(password, ADMIN_PASSWORD)
        if user_ok and pwd_ok:
            session.permanent = True
            session['admin_logged_in'] = True
            session['admin_username'] = username
            session['login_at'] = datetime.now().isoformat()
            # 防止会话固定
            session.regenerate if hasattr(session, 'regenerate') else None
            return redirect(url_for('admin_page'))
        else:
            error = '用户名或密码错误'
    return render_template_string(ADMIN_LOGIN_HTML, error=error)


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login_page'))


@app.route('/api/admin/login', methods=['POST'])
@rate_limit(10, 'admin_login')
def api_admin_login():
    """JSON登录接口（API方式进入后台，供脚本调用）"""
    try:
        data = request.get_json(silent=True) or {}
        username = (data.get('username', '') or '').strip()
        password = data.get('password', '') or ''
    except Exception:
        username = ''
        password = ''
    # 如果JSON为空，尝试form
    if not username:
        username = (request.form.get('username', '') or '').strip()
    if not password:
        password = request.form.get('password', '') or ''

    user_ok = secrets.compare_digest(username, ADMIN_USERNAME)
    pwd_ok = secrets.compare_digest(password, ADMIN_PASSWORD)
    if user_ok and pwd_ok:
        session.permanent = True
        session['admin_logged_in'] = True
        session['admin_username'] = username
        session['login_at'] = datetime.now().isoformat()
        return jsonify({
            'success': True,
            'message': '登录成功',
            'username': username,
            'loginAt': session['login_at']
        })
    return jsonify({'success': False, 'message': '用户名或密码错误'}), 401


@app.route('/api/admin/logout', methods=['POST', 'GET'])
def api_admin_logout():
    session.clear()
    return jsonify({'success': True, 'message': '已退出登录'})


@app.route('/api/lottery/record', methods=['POST'])
@rate_limit(RATE_LIMIT_LOTTERY, 'add_record')
def add_record():
    data = request.get_json() or {}
    cos_name = (data.get('cosName', '') or '').strip()
    wechat_id = (data.get('wechatId', '') or '').strip()

    if not data:
        return jsonify({'success': False, 'message': 'No data'}), 400

    timestamp = data.get('timestamp', datetime.now().isoformat())

    # 长度限制，防垃圾数据
    if len(cos_name) > 64 or len(wechat_id) > 64:
        return jsonify({'success': False, 'message': '内容过长'}), 400

    # 只需 COS 名称即可参与，微信号选填
    if not cos_name:
        return jsonify({'success': False, 'message': '请填写COS名称'}), 400

    # IP 每日抽奖次数限制（已放宽，仅防单IP刷爆）
    ok, msg = check_daily_lottery_limit(cos_name, wechat_id)
    if not ok:
        return jsonify({'success': False, 'message': msg}), 429

    records = load_records()

    # 同一COS名只能抽一次（比较时两侧均strip，兼容旧数据可能有空格）
    existing = None
    for r in records:
        if (r.get('cosName') or '').strip() == cos_name:
            existing = r
            break

    if existing:
        # 重复提交：扣回本次已计入的IP次数
        ip = get_client_ip()
        today = datetime.now().strftime('%Y-%m-%d')
        if daily_lottery_store.get(ip, {}).get(today, 0) > 0:
            daily_lottery_store[ip][today] -= 1
        return jsonify({
            'success': False,
            'message': '您已经参与过抽奖了',
            'existing': True,
            'record': existing
        }), 409

    # 【50人抽奖池机制】服务端决定中奖结果，忽略前端传入的 prizeLevel（防作弊）
    prize_level, prize_name = draw_from_pool()

    record_id = int(time.time() * 1000) + secrets.randbelow(1000)  # 加随机数防碰撞
    client_ip = get_client_ip()

    record = {
        'id': record_id,
        'cosName': cos_name,
        'wechatId': wechat_id,
        'ip': client_ip,
        'prizeLevel': prize_level,
        'prizeName': prize_name,
        'timestamp': timestamp,
        'timeStr': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'photoUrl': None,
        'photoUploaded': False
    }

    records.append(record)
    save_records(records)

    return jsonify({'success': True, 'record': record})


@app.route('/api/lottery/check', methods=['POST'])
@rate_limit(RATE_LIMIT_GENERAL, 'check_user')
def check_user():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data'}), 400

    cos_name = (data.get('cosName', '') or '').strip()
    wechat_id = (data.get('wechatId', '') or '').strip()

    if len(cos_name) > 64 or len(wechat_id) > 64:
        return jsonify({'success': False, 'message': '内容过长'}), 400

    if not cos_name:
        return jsonify({'success': True, 'exists': False, 'record': None})

    records = load_records()

    # 比较时两侧均strip，兼容存储值可能有前后空格的旧数据
    for r in records:
        if (r.get('cosName') or '').strip() == cos_name:
            return jsonify({
                'success': True,
                'exists': True,
                'record': r
            })

    return jsonify({
        'success': True,
        'exists': False,
        'record': None,
        'no_record_hint': True
    })


@app.route('/api/lottery/records', methods=['GET'])
@admin_required
@rate_limit(RATE_LIMIT_GENERAL, 'get_records')
def get_records():
    records = load_records()
    records_sorted = sorted(records, key=lambda x: x['id'], reverse=True)
    # 从抽奖池获取真实剩余
    pool_status = get_pool_status()
    return jsonify({
        'success': True,
        'records': records_sorted,
        'total': len(records_sorted),
        'firstPrizeRemaining': pool_status['firstRemaining'],
        'firstPrizeTotal': LOTTERY_FIRST_COUNT,
        'firstPrizeUsed': LOTTERY_FIRST_COUNT - pool_status['firstRemaining'],
        'secondPrizeRemaining': pool_status['secondRemaining'],
        'secondPrizeTotal': LOTTERY_SECOND_COUNT,
        'poolTotal': pool_status['total'],
        'poolDrawn': pool_status['drawn'],
        'poolRemaining': pool_status['remaining'],
    })


@app.route('/api/lottery/reset/<int:record_id>', methods=['POST'])
@admin_required
@rate_limit(30, 'reset_record')
def reset_lottery_chance(record_id):
    """
    重置某用户的抽奖机会：
    1. 删除对应记录（COS+微信号判断自然失效，该用户可重新抽奖）
    2. 清除当日该IP的抽奖次数限制（IP当日计数器归零）
    3. 如果有照片，一并删除服务器上的图片文件
    """
    records = load_records()
    target = None
    for r in records:
        if r['id'] == record_id:
            target = r
            break
    if not target:
        return jsonify({'success': False, 'message': '记录不存在'}), 404

    # ★ 检查是否有用户自己上传的照片，有则拒绝重置（文件归用户本人所有）
    user_photos = [p for p in (target.get('photos') or []) if p.get('uploadedBy') == 'user']
    if user_photos:
        return jsonify({
            'success': False,
            'message': f'该记录下有 {len(user_photos)} 张用户本人在前端上传的照片，管理员无权重置。请先让用户本人撤回/删除照片后再操作'
        }), 403

    # 1. 清除该IP当日的抽奖计数器（恢复IP抽奖机会）
    ip = target.get('ip') or ''
    today = datetime.now().strftime('%Y-%m-%d')
    if ip and ip in daily_lottery_store and today in daily_lottery_store[ip]:
        daily_lottery_store[ip][today] = 0

    # 2. 清理照片文件：
    #    · 用户已同意公开（publicApproved=True）的图：管理员无权删除，保留原状（核心权限原则）
    #    · 未被同意公开的图：一并删除服务器文件，避免孤儿文件
    deleted_urls = []

    def _del_one_photo(photo_obj):
        if not photo_obj or not photo_obj.get('photoUrl'):
            return
        try:
            filename = os.path.basename(photo_obj['photoUrl'])
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(filepath) and os.path.isfile(filepath):
                os.remove(filepath)
                deleted_urls.append(photo_obj['photoUrl'])
        except Exception:
            pass

    # 兼容旧结构（单图）
    has_approved_any = any(p.get('publicApproved') for p in target.get('photos', []) if isinstance(target.get('photos'), list))
    if not has_approved_any:
        if target.get('photoUploaded') and target.get('photoUrl'):
            _del_one_photo({'photoUrl': target['photoUrl']})

    # 多图结构：逐个检查权限后删除未同意的
    photos = target.get('photos')
    if isinstance(photos, list):
        for p in photos:
            if p.get('publicApproved'):
                # 绝对不删用户已同意公开的图
                continue
            _del_one_photo(p)

    # 3. 删除记录（核心：这样 cosName+wechatId 就找不到记录了，自然可以重新抽）
    records = [r for r in records if r['id'] != record_id]
    save_records(records)

    return jsonify({
        'success': True,
        'message': '已重置：记录已删除 + IP当日限制已解除，该用户可重新抽奖',
        'clearedIp': ip,
        'remaining': len(records),
        'deletedPhotoUrls': deleted_urls,
    })


@app.route('/api/lottery/first-prize-remaining', methods=['GET'])
@rate_limit(RATE_LIMIT_GENERAL, 'first_prize')
def get_first_prize_remaining():
    pool_status = get_pool_status()
    return jsonify({
        'success': True,
        'remaining': pool_status['firstRemaining'],
        'total': LOTTERY_FIRST_COUNT,
        'used': LOTTERY_FIRST_COUNT - pool_status['firstRemaining'],
        'secondRemaining': pool_status['secondRemaining'],
        'secondTotal': LOTTERY_SECOND_COUNT,
        'secondUsed': LOTTERY_SECOND_COUNT - pool_status['secondRemaining'],
        'poolTotal': pool_status['total'],
        'poolDrawn': pool_status['drawn'],
        'poolRemaining': pool_status['remaining'],
    })


@app.route('/api/lottery/photo/<int:record_id>', methods=['GET'])
@rate_limit(RATE_LIMIT_GENERAL, 'get_photo')
def get_photo(record_id):
    """获取某条记录的所有照片（用户端查看自己的图用）"""
    records = load_records()
    for r in records:
        if r['id'] == record_id:
            # 返回按位置升序排好的所有图
            photos_sorted = sorted(r.get('photos', []), key=lambda x: (x.get('photoPosition', 999), x.get('id', 0)))
            return jsonify({
                'success': True,
                'photoUploaded': len(photos_sorted) > 0,
                'photoCount': len(photos_sorted),
                'photoUrl': photos_sorted[0]['photoUrl'] if photos_sorted else None,
                'photos': photos_sorted,
                'maxPhotos': MAX_PHOTOS_PER_RECORD,
                'record': {
                    'id': r['id'],
                    'cosName': r.get('cosName'),
                    'prizeLevel': r.get('prizeLevel'),
                    'prizeName': r.get('prizeName')
                }
            })
    return jsonify({'success': False, 'message': 'Record not found'}), 404


@app.route('/api/lottery/photo/<int:record_id>', methods=['POST'])
@admin_required
@rate_limit(10, 'upload_photo')  # 上传接口更严
def upload_photo(record_id):
    """上传照片（管理员端）
    - form data: photo=文件, photoPosition=整数(可选,1..MAX)
    - 语义：『位置槽』语义（1..MAX_PHOTOS_PER_RECORD）共9个位置，每个位置1张
      · 若该位置为空 → 直接写入该位置
      · 若该位置已有照片 且 旧照片未被用户同意公开 → 覆盖旧照片（删旧文件+替换为新文件）
      · 若该位置已有照片 且 旧照片【已被用户同意公开】 → 直接拒绝（管理员无权更改/覆盖用户已同意的照片）
    - 未传 photoPosition → 自动选第一个空位（1..9）
    - 绝对不能修改或覆盖任何 publicApproved=True 的照片（核心权限原则）
    """
    if 'photo' not in request.files:
        return jsonify({'success': False, 'message': 'No file'}), 400

    file = request.files['photo']
    if file.filename == '' or file.filename is None:
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    # 解析上传位置序号（1-based）
    try:
        photo_position_raw = request.form.get('photoPosition', None)
        photo_position = int(photo_position_raw) if photo_position_raw not in (None, '') else None
    except (ValueError, TypeError):
        photo_position = None

    # 1. 先过一层后缀白名单
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': '不支持的文件类型，仅支持 JPG/PNG/GIF/WebP'}), 400

    # 2. 严格检查文件是不是真图片（读魔数，不信Content-Type和后缀）
    is_img, real_ext = verify_file_is_image(file)
    if not is_img:
        return jsonify({'success': False, 'message': '文件不是合法的图片，请上传真实图片'}), 400

    # 3. 检查记录是否存在
    records = load_records()
    record = None
    for r in records:
        if r['id'] == record_id:
            record = r
            break
    if record is None:
        return jsonify({'success': False, 'message': 'Record not found'}), 404

    current_photos = record.get('photos', []) or []
    used_positions = set()
    for p in current_photos:
        pp = int(p.get('photoPosition', 0) or 0)
        if 1 <= pp <= MAX_PHOTOS_PER_RECORD:
            used_positions.add(pp)

    # 4. 决定最终位置：不传→自动选第一个空位；超出范围→裁剪；位置已满但传了相同位置→走覆盖逻辑
    if photo_position is None:
        final_position = None
        for i in range(1, MAX_PHOTOS_PER_RECORD + 1):
            if i not in used_positions:
                final_position = i
                break
        if final_position is None:
            return jsonify({
                'success': False,
                'message': f'已满{MAX_PHOTOS_PER_RECORD}张，不能再上传，请先删除未同意公开的照片'
            }), 400
    else:
        final_position = max(1, min(photo_position, MAX_PHOTOS_PER_RECORD))

    # 5. 检查该位置是否有旧图：若旧图已被用户同意公开，管理员无权覆盖
    old_photo = None
    for p in current_photos:
        if (int(p.get('photoPosition', 0) or 0)) == final_position:
            old_photo = p
            break
    if old_photo is not None and old_photo.get('publicApproved'):
        return jsonify({
            'success': False,
            'message': f'位置#{final_position}的照片已被用户本人同意公开到公共墙，管理员无权修改或覆盖'
        }), 403

    # 5.1 空位置已满检查
    if old_photo is None and len(current_photos) >= MAX_PHOTOS_PER_RECORD:
        return jsonify({
            'success': False,
            'message': f'每条记录最多只能上传 {MAX_PHOTOS_PER_RECORD} 张照片（当前已满）'
        }), 400

    # 6. 二次重编码图片（销毁木马字节）+ 随机文件名，不准用原名
    rewritten, file_bytes, final_ext = safe_rewrite_image(file, real_ext)
    if file_bytes is None:
        return jsonify({'success': False, 'message': '图片损坏，无法处理'}), 400

    photo_id = (max((int(p.get('id', 0) or 0) for p in current_photos), default=0)) + 1
    rand_name = f"{record_id}_{photo_id}_{int(time.time()*1000)}_{secrets.token_hex(6)}.{final_ext}"
    filepath = os.path.join(UPLOAD_FOLDER, rand_name)
    init_data()
    with open(filepath, 'wb') as f:
        f.write(file_bytes)
    photo_url = f"/data/photos/{rand_name}"

    # 7. 写入/替换：若位置相同→覆盖旧图（先删旧文件），再替换；否则直接加
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_photo = {
        'id': photo_id,
        'photoUrl': photo_url,
        'photoPosition': final_position,
        'publicApproved': False,        # 管理员无权代用户同意公开
        'publicApprovedAt': None,       # 只有用户本人点『同意公开』才能写入此字段
        'uploadedAt': now,
    }

    if old_photo is not None:
        # 先删旧图物理文件（已经确认publicApproved=False，所以可以删）
        old_filename = (old_photo.get('photoUrl') or '').split('/')[-1]
        if old_filename:
            old_fp = os.path.join(UPLOAD_FOLDER, old_filename)
            if os.path.exists(old_fp) and os.path.isfile(old_fp):
                try:
                    os.remove(old_fp)
                except Exception:
                    pass
        # 替换
        for idx, p in enumerate(current_photos):
            if int(p.get('photoPosition', 0) or 0) == final_position:
                current_photos[idx] = new_photo
                break
    else:
        current_photos.append(new_photo)

    # 重新排序（按photoPosition升序，确保后续photoUrl等快捷字段稳定）
    current_photos.sort(key=lambda x: (int(x.get('photoPosition', 999) or 999), int(x.get('id', 0) or 0)))
    record['photos'] = current_photos
    record['photoCount'] = len(current_photos)
    record['photoUploaded'] = len(current_photos) > 0
    record['photoUrl'] = current_photos[0]['photoUrl'] if len(current_photos) > 0 else None

    save_records(records)
    return jsonify({
        'success': True,
        'photoId': photo_id,
        'photoUrl': photo_url,
        'photoPosition': final_position,
        'rewritten': rewritten,
        'photoCount': len(current_photos),
        'maxPhotos': MAX_PHOTOS_PER_RECORD,
        'photos': current_photos,
    })


@app.route('/api/lottery/photo/<int:record_id>/<int:photo_id>', methods=['DELETE'])
@admin_required
@rate_limit(20, 'delete_photo')
def delete_single_photo(record_id, photo_id):
    """删除某一张具体的照片（管理员端）
    关键权限：只要这张图 publicApproved=True（用户已同意公开到公共墙）→ 403 拒绝，不准删、不准改、不准动文件
    """
    records = load_records()
    record = None
    for r in records:
        if r['id'] == record_id:
            record = r
            break
    if record is None:
        return jsonify({'success': False, 'message': 'Record not found'}), 404
    photos = record.get('photos', []) or []
    target = None
    for p in photos:
        if int(p.get('id', 0) or 0) == photo_id:
            target = p
            break
    if target is None:
        return jsonify({'success': False, 'message': 'Photo not found'}), 404

    # ========== 先做权限校验！再动任何文件！顺序不能改！ ==========
    if target.get('publicApproved'):
        return jsonify({
            'success': False,
            'message': '该照片已由用户本人同意公开到公共墙，管理员无权修改或删除'
        }), 403

    # ★ 新增：用户自己上传的照片，管理员无权删除
    if target.get('uploadedBy') == 'user':
        return jsonify({
            'success': False,
            'message': '该照片由用户本人在前端上传，管理员无权删除。如需删除请联系用户本人操作'
        }), 403

    # 权限通过后再删物理文件
    filename = (target.get('photoUrl') or '').split('/')[-1]
    if filename:
        fp = os.path.join(UPLOAD_FOLDER, filename)
        if os.path.exists(fp) and os.path.isfile(fp):
            try:
                os.remove(fp)
            except Exception:
                pass

    photos.remove(target)
    photos.sort(key=lambda x: (int(x.get('photoPosition', 999) or 999), int(x.get('id', 0) or 0)))
    record['photos'] = photos
    record['photoCount'] = len(photos)
    record['photoUploaded'] = len(photos) > 0
    record['photoUrl'] = photos[0]['photoUrl'] if len(photos) > 0 else None
    save_records(records)
    return jsonify({
        'success': True,
        'photoCount': len(photos),
        'photos': photos,
    })


# 兼容老接口 DELETE /api/lottery/photo/<rid>（不传photo_id的情况）：批量删除该记录下所有未同意公开的照片
# 关键约束：只要该记录里【任何一张】被用户同意公开过 → 就整体拒绝，避免管理员把剩余照片删了导致UI/数据歧义
@app.route('/api/lottery/photo/<int:record_id>', methods=['DELETE'])
@admin_required
@rate_limit(20, 'delete_photo_legacy')
def delete_photo_legacy(record_id):
    records = load_records()
    record = None
    for r in records:
        if r['id'] == record_id:
            record = r
            break
    if record is None:
        return jsonify({'success': False, 'message': 'Record not found'}), 404
    photos = record.get('photos', []) or []
    if len(photos) == 0:
        return jsonify({'success': True, 'photoCount': 0, 'photos': []})

    any_approved = any(bool(p.get('publicApproved')) for p in photos)
    if any_approved:
        return jsonify({
            'success': False,
            'message': '该记录下存在已由用户本人同意公开的照片，管理员无权批量删除，请到具体位置删除未同意的那几张'
        }), 403

    # ★ 检查是否有用户自己上传的照片
    any_user_uploaded = any(p.get('uploadedBy') == 'user' for p in photos)
    if any_user_uploaded:
        return jsonify({
            'success': False,
            'message': '该记录下存在用户本人在前端上传的照片，管理员无权批量删除，请联系用户本人操作'
        }), 403

    # 全部未同意公开 → 全部删除
    for target in photos:
        filename = (target.get('photoUrl') or '').split('/')[-1]
        if filename:
            fp = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(fp) and os.path.isfile(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
    record['photos'] = []
    record['photoCount'] = 0
    record['photoUploaded'] = False
    record['photoUrl'] = None
    save_records(records)
    return jsonify({'success': True, 'photoCount': 0, 'photos': []})


@app.route('/data/photos/<path:filename>')
@rate_limit(RATE_LIMIT_GENERAL, 'serve_photo')
def serve_photo(filename):
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        abort(404)
    if not allowed_file(safe_name):
        abort(404)
    filepath = os.path.join(UPLOAD_FOLDER, safe_name)
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, safe_name)


# ======================= QR码 / 联系方式 配置 =======================

@app.route('/api/config')
@rate_limit(RATE_LIMIT_GENERAL, 'config')
def get_config():
    """获取站点公开配置（QR码URL、QQ号、微信号）"""
    cfg = load_config()
    return jsonify({
        'qq_code': cfg.get('qq_code'),
        'wechat_code': cfg.get('wechat_code'),
        'qq_number': cfg.get('qq_number', ''),
        'wechat_id': cfg.get('wechat_id', '')
    })


@app.route('/data/qrcodes/<path:filename>')
@rate_limit(RATE_LIMIT_GENERAL, 'serve_qrcode')
def serve_qrcode(filename):
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        abort(404)
    if not allowed_file(safe_name):
        abort(404)
    filepath = os.path.join(QR_FOLDER, safe_name)
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        abort(404)
    return send_from_directory(QR_FOLDER, safe_name)


@app.route('/api/admin/qrcode', methods=['POST'])
@admin_required
@rate_limit(10, 'admin_qrcode')
def admin_upload_qrcode():
    """管理员上传/更新QQ或微信二维码图片"""
    channel = request.form.get('channel', '').strip().lower()
    if channel not in ('qq', 'wechat'):
        return jsonify({'success': False, 'message': '参数错误，channel 必须是 qq 或 wechat'}), 400
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '未选择文件'}), 400
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'success': False, 'message': '未选择文件'}), 400
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': '仅支持 PNG/JPG/JPEG/GIF/WebP 格式'}), 400
    mime = file.mimetype
    if mime not in ALLOWED_MIME_TYPES:
        return jsonify({'success': False, 'message': '不支持的图片格式'}), 400

    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f'{channel}_code.{ext}'
    filepath = os.path.join(QR_FOLDER, filename)
    file.save(filepath)

    for old in os.listdir(QR_FOLDER):
        if old.startswith(f'{channel}_code.') and old != filename:
            try:
                os.remove(os.path.join(QR_FOLDER, old))
            except Exception:
                pass

    cfg = load_config()
    cfg[f'{channel}_code'] = f'/data/qrcodes/{filename}'
    save_config(cfg)

    return jsonify({'success': True, 'url': f'/data/qrcodes/{filename}', 'channel': channel})


@app.route('/api/admin/config', methods=['POST'])
@admin_required
@rate_limit(10, 'admin_config')
def admin_update_config():
    """管理员更新联系方式（QQ号、微信号文本）"""
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    if 'qq_number' in data:
        cfg['qq_number'] = str(data.get('qq_number', '')).strip()
    if 'wechat_id' in data:
        cfg['wechat_id'] = str(data.get('wechat_id', '')).strip()
    save_config(cfg)
    return jsonify({'success': True, 'config': cfg})


# ======================= 缩略图服务（带宽优化） =======================
# 路由：/data/thumb/<filename>
# 生成 max 480px 宽的缩略图并缓存到 data/photos/_thumb/
# 前端列表/九宫格使用缩略图，点击大图才加载原图
THUMB_FOLDER = os.path.join(UPLOAD_FOLDER, '_thumb')
os.makedirs(THUMB_FOLDER, exist_ok=True)

@app.route('/data/thumb/<path:filename>')
@rate_limit(RATE_LIMIT_GENERAL, 'serve_thumb')
def serve_thumb(filename):
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        abort(404)
    if not allowed_file(safe_name):
        abort(404)
    # 检查缓存
    thumb_name = safe_name.rsplit('.', 1)[0] + '_thumb.jpg'
    thumb_path = os.path.join(THUMB_FOLDER, thumb_name)
    if os.path.exists(thumb_path) and os.path.isfile(thumb_path):
        resp = send_from_directory(THUMB_FOLDER, thumb_name)
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp
    # 生成缩略图
    src_path = os.path.join(UPLOAD_FOLDER, safe_name)
    if not os.path.exists(src_path) or not os.path.isfile(src_path):
        abort(404)
    try:
        from PIL import Image
        import io
        img = Image.open(src_path)
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode != 'RGB':
            img = img.convert('RGB')
        # 缩放到 max 480px 宽
        w, h = img.size
        if w > 480:
            ratio = 480 / float(w)
            new_h = max(1, int(round(h * ratio)))
            try:
                img = img.resize((480, new_h), Image.LANCZOS)
            except Exception:
                try:
                    img = img.resize((480, new_h), Image.BILINEAR)
                except Exception:
                    pass
        img.save(thumb_path, format='JPEG', quality=72, optimize=True)
        resp = send_from_directory(THUMB_FOLDER, thumb_name)
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp
    except Exception:
        # 生成失败，回退到原图
        return send_from_directory(UPLOAD_FOLDER, safe_name)


# ======================= 静态文件缓存头 =======================
@app.after_request
def add_cache_headers(resp):
    # 图片文件：缓存 1 天
    if request.path.startswith('/data/photos/') or request.path.startswith('/data/thumb/'):
        resp.headers['Cache-Control'] = 'public, max-age=86400'
    # CSS/JS：缓存 1 小时
    elif request.path.endswith('.css') or request.path.endswith('.js'):
        resp.headers['Cache-Control'] = 'public, max-age=3600'
    # HTML：不缓存
    elif request.path.endswith('.html') or request.path == '/':
        resp.headers['Cache-Control'] = 'no-cache'
    return resp


# ======================= A1 用户端极简上传照片 =======================
# 端点：POST /api/lottery/self/<int:record_id>/photo
# 鉴权：form/data 中必须携带 cosName + wechatId，和记录里存的完全匹配才算本人
# 语义：跟管理员 upload_photo 完全一致（位置槽 1..9 / 覆盖同位置未公开图 / 已公开图不可覆盖）
@app.route('/api/lottery/self/<int:record_id>/photo', methods=['POST'])
@rate_limit(15, 'self_upload_photo')
def self_upload_photo(record_id):
    if 'photo' not in request.files:
        return jsonify({'success': False, 'message': '请先选择图片文件'}), 400
    file = request.files['photo']
    if not getattr(file, 'filename', ''):
        return jsonify({'success': False, 'message': '未选择文件'}), 400

    # ==== 身份校验：用户本人（COS名 匹配即可）====
    body_cos = ((request.form.get('cosName') if request.method == 'POST' else None) or '').strip()
    body_wx = ((request.form.get('wechatId') if request.method == 'POST' else None) or '').strip()
    if not body_cos:
        try:
            if request.content_length and request.is_json:
                j = request.get_json(silent=True) or {}
                body_cos = (j.get('cosName') or '').strip()
                body_wx = (j.get('wechatId') or '').strip()
        except Exception:
            pass
    if not body_cos:
        body_cos = (request.form.get('cosName') or '').strip()
        body_wx = (request.form.get('wechatId') or '').strip()
    if not body_cos:
        return jsonify({'success': False, 'message': '身份校验失败，请返回首页重新登记信息'}), 401

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': '不支持的文件类型，仅支持 JPG/PNG/GIF/WebP'}), 400
    is_img, real_ext = verify_file_is_image(file)
    if not is_img:
        return jsonify({'success': False, 'message': '上传的文件不是合法图片'}), 400

    records = load_records()
    record = next((r for r in records if int(r.get('id', 0) or 0) == int(record_id)), None)
    if record is None:
        return jsonify({'success': False, 'message': '抽奖记录不存在，请重新抽奖'}), 404

    if (record.get('cosName') or '').strip() != body_cos:
        return jsonify({'success': False, 'message': '身份不匹配，只能上传你本人抽奖记录下的照片'}), 403

    # 解析上传位置序号
    try:
        pp_raw = request.form.get('photoPosition', None)
        photo_position = int(pp_raw) if pp_raw not in (None, '') else None
    except (ValueError, TypeError):
        photo_position = None

    current_photos = list(record.get('photos', []) or [])
    used_positions = set()
    for p in current_photos:
        pp = int(p.get('photoPosition', 0) or 0)
        if 1 <= pp <= MAX_PHOTOS_PER_RECORD:
            used_positions.add(pp)

    if photo_position is None:
        final_position = next((i for i in range(1, MAX_PHOTOS_PER_RECORD + 1) if i not in used_positions), None)
        if final_position is None:
            return jsonify({'success': False, 'message': f'已满{MAX_PHOTOS_PER_RECORD}张，不能再传'}), 400
    else:
        final_position = max(1, min(int(photo_position), MAX_PHOTOS_PER_RECORD))

    old_photo = next((p for p in current_photos if (int(p.get('photoPosition', 0) or 0)) == final_position), None)
    if old_photo is not None and old_photo.get('publicApproved'):
        return jsonify({'success': False, 'message': f'位置#{final_position}已被你本人同意公开，无法覆盖或修改'}), 403
    if old_photo is None and len(current_photos) >= MAX_PHOTOS_PER_RECORD:
        return jsonify({'success': False, 'message': f'已满{MAX_PHOTOS_PER_RECORD}张，不能再传'}), 400

    # ====== 写文件（原子 + 安全重命名 + Pillow压缩） ======
    file.seek(0)
    ok, file_bytes, final_ext = safe_rewrite_image(file, real_ext)
    if file_bytes is None:
        return jsonify({'success': False, 'message': '图片处理失败，请更换图片重试'}), 400
    if final_ext and final_ext != real_ext:
        real_ext = final_ext
    rewritten = ok
    safe_fn = secure_filename(f"user_{record_id}_{final_position}_{int(time.time()*1000)}.{real_ext}") or f"userup_{int(time.time()*1000)}.{real_ext}"
    save_path = os.path.join(UPLOAD_FOLDER, safe_fn)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix='.selfup_', suffix='.' + real_ext, dir=UPLOAD_FOLDER)
    try:
        with os.fdopen(tmp_fd, 'wb') as tf:
            tf.write(file_bytes)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, save_path)
        # tempfile.mkstemp 创建的文件权限是 0600，nginx 用户无法直接读取；
        # 虽然图片通过 gunicorn(root) 代理返回不影响访问，但统一改成 0644 更安全兼容
        try:
            os.chmod(save_path, 0o644)
        except Exception:
            pass
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return jsonify({'success': False, 'message': '文件保存失败，请稍后重试'}), 500

    # 删除旧图文件（如果有，且未公开）
    if old_photo:
        old_fn = (old_photo.get('photoUrl') or '').split('/')[-1]
        if old_fn:
            ofp = os.path.join(UPLOAD_FOLDER, old_fn)
            try:
                if os.path.exists(ofp) and os.path.isfile(ofp):
                    os.remove(ofp)
            except Exception:
                pass
        current_photos = [p for p in current_photos if (int(p.get('photoPosition', 0) or 0)) != final_position]
        rewritten = True

    photo_id = int((record.get('lastPhotoId') or 0)) + 1
    record['lastPhotoId'] = photo_id
    photo_url = f'/data/photos/{safe_fn}'
    new_photo = {
        'id': photo_id,
        'photoUrl': photo_url,
        'photoPosition': final_position,
        'publicApproved': False,
        'approvedBySelf': False,
        'publicApprovedAt': None,
        'uploadedBy': 'user',
        'uploadedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    current_photos.append(new_photo)
    current_photos.sort(key=lambda x: (int(x.get('photoPosition', 999) or 999), int(x.get('id', 0) or 0)))
    record['photos'] = current_photos
    record['photoCount'] = len(current_photos)
    record['photoUploaded'] = len(current_photos) > 0
    record['photoUrl'] = current_photos[0]['photoUrl'] if len(current_photos) > 0 else None

    save_records(records)
    return jsonify({
        'success': True,
        'photoId': photo_id,
        'photoUrl': photo_url,
        'photoPosition': final_position,
        'rewritten': rewritten,
        'photoCount': len(current_photos),
        'maxPhotos': MAX_PHOTOS_PER_RECORD,
        'photos': current_photos,
    })


@app.route('/api/lottery/photos/public', methods=['GET'])
@rate_limit(RATE_LIMIT_GENERAL, 'public_photos')
def public_photos():
    """公共照片墙接口（未登录可访问）：
    - 关键：仅返回用户本人通过 /approve 接口同意公开的照片（publicApproved=true）
    - 未经用户同意的照片绝对不会出现在这里，管理员也无法绕过
    - 单位细化到单张图（而不是整条记录），每张图一个 card
    - 每张图内部按 photoPosition 升序；多张图之间按 publicApprovedAt 倒序（最新同意的在上）
    - limit 默认 50，最大 200；支持 since_id（since_id=照片record内部photo的globalId组合数）
    """
    try:
        limit = max(1, min(200, int(request.args.get('limit', 50))))
    except (ValueError, TypeError):
        limit = 50
    try:
        since_combined = int(request.args.get('since_id', 0))
    except (ValueError, TypeError):
        since_combined = 0

    records = load_records()
    items = []
    for r in records:
        rid = int(r.get('id', 0) or 0)
        cn = (r.get('cosName') or '匿名COSER').strip() or '匿名COSER'
        if len(cn) > 2:
            masked_cn = cn[0] + '·' + cn[-1]
        else:
            masked_cn = cn
        prize_level = int(r.get('prizeLevel') or 0)
        prize_name = r.get('prizeName') or ''
        # 只取该记录内用户明确同意公开的那几张图
        approved_photos = [
            p for p in r.get('photos', [])
            if p.get('publicApproved') and p.get('photoUrl')
        ]
        # 记录内按 photoPosition 升序排（用户设定好的位置顺序）
        approved_photos.sort(key=lambda p: (p.get('photoPosition', 999), p.get('id', 0)))
        for p in approved_photos:
            # 生成全局唯一的 combined id（rid左移24位 | photo_id），用于 since_id 增量拉取
            combined_id = (rid << 24) | (int(p.get('id', 0)) & 0xFFFFFF)
            if since_combined and combined_id <= since_combined:
                continue
            items.append({
                'id': combined_id,
                'recordId': rid,
                'photoId': int(p.get('id', 0)),
                'photoUrl': p['photoUrl'],
                'photoPosition': int(p.get('photoPosition', 0)),
                'prizeLevel': prize_level,
                'prizeName': prize_name,
                'cosNameMasked': masked_cn,
                'timeStr': p.get('publicApprovedAt') or r.get('timeStr') or '',
                'approvedAt': p.get('publicApprovedAt'),
            })
    # 全局按同意时间倒序，时间相同的按 record 倒序，record 相同按 position 升序
    items.sort(key=lambda x: (
        -(0 if not x.get('approvedAt') else int(datetime.strptime(x['approvedAt'], '%Y-%m-%d %H:%M:%S').timestamp() if isinstance(x.get('approvedAt'), str) else 0)),
        -x.get('recordId', 0),
        x.get('photoPosition', 999),
    ))
    total = len(items)
    items = items[:limit]
    return jsonify({
        'success': True,
        'total': total,
        'since_id': since_combined,
        'photos': items,
    })


# =====================================================================
# 用户端：同意公开自己的某张照片（公共墙显示的唯一权限入口）
# 这个接口不能带 admin_required，必须用 COS名称+微信号 校验身份
# 管理员也不能调用此接口的反向操作（没有 revoke 接口），一旦用户同意即永久公开
# =====================================================================
@app.route('/api/lottery/photo/<int:record_id>/<int:photo_id>/approve', methods=['POST'])
@rate_limit(20, 'approve_public')
def user_approve_public(record_id, photo_id):
    """用户端：点击『同意公开到大家照片』按钮 → 把 publicApproved 置为 true
    不再校验身份，前端点击即公开
    """
    records = load_records()
    record = None
    for r in records:
        if r['id'] == record_id:
            record = r
            break
    if record is None:
        return jsonify({'success': False, 'message': 'Record not found'}), 404

    photos = record.get('photos', [])
    target = None
    for p in photos:
        if p.get('id') == photo_id:
            target = p
            break
    if target is None or not target.get('photoUrl'):
        return jsonify({'success': False, 'message': 'Photo not found'}), 404

    # 幂等：已经同意过的直接返回成功
    if target.get('publicApproved'):
        return jsonify({
            'success': True,
            'alreadyApproved': True,
            'photoId': photo_id,
            'publicApproved': True,
            'publicApprovedAt': target.get('publicApprovedAt'),
        })

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    target['publicApproved'] = True
    target['publicApprovedAt'] = now
    save_records(records)
    return jsonify({
        'success': True,
        'photoId': photo_id,
        'recordId': record_id,
        'publicApproved': True,
        'publicApprovedAt': now,
        'message': '已同意公开到大家照片墙（可随时撤回）',
    })


# =====================================================================
# 用户端：撤回已公开的照片（从公共墙撤销）
# 不用 admin_required，用户本人通过 COS名+微信号 验证身份即可操作
# =====================================================================
@app.route('/api/lottery/photo/<int:record_id>/<int:photo_id>/withdraw', methods=['POST'])
@rate_limit(10, 'withdraw_photo')
def user_withdraw_public(record_id, photo_id):
    """用户撤回已同意公开的照片：publicApproved ← false
    不再校验身份
    """
    records = load_records()
    record = None
    for r in records:
        if r['id'] == record_id:
            record = r
            break
    if record is None:
        return jsonify({'success': False, 'message': '记录不存在'}), 404

    photos = record.get('photos', [])
    target = None
    for p in photos:
        if p.get('id') == photo_id:
            target = p
            break
    if target is None or not target.get('photoUrl'):
        return jsonify({'success': False, 'message': '照片不存在'}), 404

    if not target.get('publicApproved'):
        return jsonify({'success': True, 'message': '该照片未公开，无需撤回'})

    target['publicApproved'] = False
    target['publicApprovedAt'] = None
    save_records(records)
    return jsonify({
        'success': True,
        'photoId': photo_id,
        'recordId': record_id,
        'publicApproved': False,
        'message': '已撤回公开，照片不再显示在「大家的照片」中',
    })


# =====================================================================
# 用户端：删除自己未公开的照片（不用 admin_required）
# =====================================================================
@app.route('/api/lottery/photo/<int:record_id>/<int:photo_id>/user-delete', methods=['POST'])
@rate_limit(10, 'user_delete_photo')
def user_delete_own_photo(record_id, photo_id):
    """用户删除自己未公开的照片（已公开的必须先撤回再删）"""
    records = load_records()
    record = None
    for r in records:
        if r['id'] == record_id:
            record = r
            break
    if record is None:
        return jsonify({'success': False, 'message': '记录不存在'}), 404

    photos = record.get('photos', [])
    target = None
    for p in photos:
        if p.get('id') == photo_id:
            target = p
            break
    if target is None or not target.get('photoUrl'):
        return jsonify({'success': False, 'message': '照片不存在'}), 404

    if target.get('publicApproved'):
        return jsonify({'success': False, 'message': '该照片已公开，请先撤回再删除'}), 400

    # 删除物理文件
    filename = (target.get('photoUrl') or '').split('/')[-1]
    if filename:
        fp = os.path.join(UPLOAD_FOLDER, filename)
        if os.path.exists(fp) and os.path.isfile(fp):
            try:
                os.remove(fp)
            except Exception:
                pass

    photos.remove(target)
    photos.sort(key=lambda x: (int(x.get('photoPosition', 999) or 999), int(x.get('id', 0) or 0)))
    record['photos'] = photos
    record['photoCount'] = len(photos)
    record['photoUploaded'] = len(photos) > 0
    record['photoUrl'] = photos[0]['photoUrl'] if len(photos) > 0 else None
    save_records(records)
    return jsonify({
        'success': True,
        'photoCount': len(photos),
        'photos': photos,
        'message': '已删除',
    })


# ================= 给摄影师留言板（用户上传照片后提修图需求） =================
@app.route('/api/lottery/message/<int:record_id>', methods=['POST'])
@rate_limit(15, 'post_message')
def post_message_to_photographer(record_id):
    """用户端：在照片下面留言，告诉摄影师想修成什么风格/修哪里"""
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    cos_name = (data.get('cosName', '') or '').strip()
    wechat_id = (data.get('wechatId', '') or '').strip()
    text_raw = (data.get('text', '') or '').strip()

    if not cos_name:
        return jsonify({'success': False, 'message': '请先填写COS名（用于验证身份）'}), 400
    if not text_raw:
        return jsonify({'success': False, 'message': '留言内容不能为空哦'}), 400
    if len(text_raw) > 500:
        return jsonify({'success': False, 'message': '留言不能超过 500 字（现在写得太长了）'}), 400

    records = load_records()
    target_record = None
    for r in records:
        if r['id'] == record_id:
            target_record = r
            break
    if target_record is None:
        return jsonify({'success': False, 'message': '抽奖记录不存在，请先去抽奖'}), 404

    # 身份校验：必须本人（只校验 COS 名）
    if (target_record.get('cosName') or '').strip() != cos_name:
        return jsonify({'success': False, 'message': '身份验证失败：COS名不匹配'}), 403

    # 确保 messages 列表存在
    if 'messages' not in target_record or not isinstance(target_record.get('messages'), list):
        target_record['messages'] = []
    msgs = target_record['messages']
    new_msg = {
        'id': (max([int(m.get('id', 0)) for m in msgs if isinstance(m, dict)] or [0])) + 1,
        'createdAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'by': 'user',
        'cosName': cos_name,
        'wechatId': wechat_id,
        'text': text_raw,
        'read': False,
        'reply': None,
        'replyAt': None,
    }
    msgs.append(new_msg)
    try:
        save_records(records)
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存失败：{str(e)[:80]}'}), 500
    return jsonify({
        'success': True,
        'message': '留言已发送给摄影师啦，对方会看到你的修图需求～',
        'newMessage': new_msg,
        'total': len(msgs),
    })


@app.route('/api/lottery/message/<int:record_id>', methods=['GET'])
@rate_limit(RATE_LIMIT_GENERAL, 'get_messages')
def get_messages_for_photographer(record_id):
    """用户端：获取该记录下的所有留言 + 摄影师回复（在照片下面展示历史列表）"""
    cos_name = (request.args.get('cosName', '') or '').strip()
    wechat_id = (request.args.get('wechatId', '') or '').strip()
    if not cos_name:
        return jsonify({'success': False, 'message': '请带上 cosName 查询'}), 400
    records = load_records()
    for r in records:
        if r['id'] == record_id:
            if (r.get('cosName') or '').strip() != cos_name:
                return jsonify({'success': False, 'message': '身份验证失败'}), 403
            msgs = r.get('messages') if isinstance(r.get('messages'), list) else []
            # 精简字段（避免泄露 wechatId 到前端其他地方）
            safe = []
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                # 🆕 如果有 reply 字段且 replyRead 不存在，补齐默认值
                reply_content = m.get('reply', None)
                has_reply = bool(reply_content and isinstance(reply_content, str) and reply_content.strip())
                reply_read_flag = m.get('replyRead', None)
                if reply_read_flag is None and has_reply:
                    # 旧数据：没有 replyRead 字段 → 默认未读（前端会用 localStorage 做二次兜底）
                    reply_read_safe = False
                else:
                    reply_read_safe = bool(reply_read_flag)
                safe.append({
                    'id': m.get('id', 0),
                    'createdAt': m.get('createdAt', ''),
                    'by': m.get('by', 'user'),
                    'cosName': m.get('cosName', ''),
                    'text': m.get('text', ''),
                    'reply': m.get('reply', None),
                    'replyAt': m.get('replyAt', None),
                    'replyRead': reply_read_safe,  # 🆕 告诉前端：这回复用户看过没
                })
            return jsonify({
                'success': True,
                'total': len(safe),
                'messages': safe,
            })
    return jsonify({'success': False, 'message': '记录不存在'}), 404


# ================= 管理员回复用户留言（摄影师修图完成后反馈给用户） =================
@app.route('/api/admin/message/<int:record_id>/<int:msg_id>/reply', methods=['POST'])
@admin_required
@rate_limit(60, 'admin_reply_message')
def admin_reply_message(record_id, msg_id):
    """管理员端：回复某条用户留言，前端会轮询/message接口拿到reply后显示"""
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    reply_raw = (data.get('reply', '') or '').strip()
    if not reply_raw:
        return jsonify({'success': False, 'message': '回复内容不能为空'}), 400
    if len(reply_raw) > 1000:
        return jsonify({'success': False, 'message': '回复太长啦，最多1000字'}), 400
    records = load_records()
    target_record = None
    for r in records:
        if r['id'] == record_id:
            target_record = r
            break
    if target_record is None:
        return jsonify({'success': False, 'message': '记录不存在'}), 404
    msgs = target_record.get('messages') if isinstance(target_record.get('messages'), list) else []
    target_msg = None
    for m in msgs:
        if isinstance(m, dict) and int(m.get('id', 0)) == int(msg_id):
            target_msg = m
            break
    if target_msg is None:
        return jsonify({'success': False, 'message': '留言不存在'}), 404
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    target_msg['reply'] = reply_raw
    target_msg['replyAt'] = now
    target_msg['read'] = True
    # 🆕 摄影师回复后，这条回复标记为"用户未读"（前端显示新回复红点）
    target_msg['replyRead'] = False
    try:
        save_records(records)
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存失败：{str(e)[:80]}'}), 500
    # 重新在内存里定位最新messages，返回给前端
    for r in load_records():
        if r['id'] == record_id:
            for m in (r.get('messages') or []):
                if isinstance(m, dict) and int(m.get('id', 0)) == int(msg_id):
                    return jsonify({'success': True, 'message': '回复已发送给用户~', 'updatedMessage': m})
    return jsonify({'success': True, 'message': '回复已发送给用户~', 'updatedMessage': target_msg})


# ================= 管理员：标记留言为已读 =================
@app.route('/api/admin/message/<int:record_id>/<int:msg_id>/read', methods=['POST'])
@admin_required
@rate_limit(120, 'admin_read_message')
def admin_mark_message_read(record_id, msg_id):
    records = load_records()
    changed = False
    for r in records:
        if r['id'] == record_id:
            msgs = r.get('messages') if isinstance(r.get('messages'), list) else []
            for m in msgs:
                if isinstance(m, dict) and int(m.get('id', 0)) == int(msg_id) and not m.get('read'):
                    m['read'] = True
                    changed = True
            break
    if changed:
        try: save_records(records)
        except Exception: pass
    return jsonify({'success': True, 'changed': changed})


@app.route('/api/admin/reset-all', methods=['POST'])
@admin_required
@rate_limit(30, 'admin_reset_all')
def admin_reset_all():
    """一键清空所有抽奖记录（测试后重置用），同时清除频率限制缓存"""
    try:
        # 备份旧记录数
        old_records = load_records()
        old_count = len(old_records)
        # 清空记录
        save_records([])
        # 清除内存中的频率限制缓存
        rate_store.clear()
        daily_lottery_store.clear()
        # 重置50人抽奖池
        reset_lottery_pool()
        return jsonify({'success': True, 'message': f'已清空 {old_count} 条抽奖记录，50人抽奖池已重置', 'count': old_count})
    except Exception as e:
        return jsonify({'success': False, 'message': f'重置失败: {str(e)}'}), 500


ADMIN_PAGE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>抽奖记录 · 漫展抽奖控制台</title>
  <link rel="stylesheet" href="/css/admin.css?v=m3">
</head>
<body>
  <!-- 左侧竖排导航 -->
  <aside class="sidebar">
    <div class="sidebar-logo">🎁</div>
    <div class="sidebar-brand-text">抽奖管理</div>
    <div class="sidebar-divider"></div>
    <a class="sidebar-link active" href="/admin" title="记录管理">
      <span>📋</span><span>记录</span>
    </a>
    <a class="sidebar-link" href="/admin/dashboard" title="数据看板">
      <span>📊</span><span>看板</span>
    </a>
    <a class="sidebar-link" href="/" title="前台首页" target="_blank" rel="noopener">
      <span>🎯</span><span>前台</span>
    </a>
    <div class="sidebar-spacer"></div>
    <div class="sidebar-avatar" title="admin">A</div>
    <a class="sidebar-logout" href="#" data-logout title="退出登录">⏻</a>
  </aside>
  <div class="sidebar-overlay" id="sidebarOverlay"></div>

  <main class="app-main">
    <!-- 顶部栏 -->
    <header class="topbar glass" style="padding: 10px 18px;">
      <div class="topbar-title-wrap">
        <div class="topbar-icon">📋</div>
        <div>
          <div class="topbar-title">抽奖记录管理</div>
          <div class="topbar-subtitle" id="topbarSubtitle">实时数据 · 每 5 秒自动刷新</div>
        </div>
      </div>
      <div class="topbar-actions">
        <button class="btn btn-ghost" onclick="loadRecords()">🔄 刷新数据</button>
        <button class="btn btn-gold" onclick="exportCSV()">⬇ 导出CSV</button>
        <button class="btn btn-danger" onclick="resetAllRecords()" style="background:linear-gradient(135deg,#EF4444,#DC2626);color:#fff;border:none;" title="清空所有抽奖记录，重置奖品库存">🗑 一键重置</button>
      </div>
    </header>

    <!-- 顶部 KPI 一行（6卡） -->
    <div class="kpi-row">
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon cyan">👥</div><span class="stat-mini-delta up">LIVE</span></div>
        <div class="stat-mini-value" id="s_total">0</div>
        <div class="stat-mini-label">总参与人数</div>
        <div class="stat-mini-bar"><div style="width:100%;background:linear-gradient(90deg,#00B4D8,#0077B6);"></div></div>
      </div>
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon gold">🏆</div><span class="stat-mini-delta up" id="s_p1_percent">0%</span></div>
        <div class="stat-mini-value" id="s_p1">0</div>
        <div class="stat-mini-label">一等奖 · 20元红包</div>
        <div class="stat-mini-bar"><div id="s_p1_bar" style="width:0%;background:linear-gradient(90deg,#FBBF24,#F59E0B);"></div></div>
      </div>
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon red">🧧</div><span class="stat-mini-delta up" id="s_p2_percent">0%</span></div>
        <div class="stat-mini-value" id="s_p2">0</div>
        <div class="stat-mini-label">二等奖 · 霞蝶手办</div>
        <div class="stat-mini-bar"><div id="s_p2_bar" style="width:0%;background:linear-gradient(90deg,#EF4444,#DC2626);"></div></div>
      </div>
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon green">🥉</div><span class="stat-mini-delta up" id="s_p3_percent">0%</span></div>
        <div class="stat-mini-value" id="s_p3">0</div>
        <div class="stat-mini-label">谢谢参与</div>
        <div class="stat-mini-bar"><div id="s_p3_bar" style="width:0%;background:linear-gradient(90deg,#06D6A0,#059669);"></div></div>
      </div>
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon green">📸</div><span class="stat-mini-delta up" id="s_up_percent">0%</span></div>
        <div class="stat-mini-value" id="s_uploaded">0</div>
        <div class="stat-mini-label">已上传照片</div>
        <div class="stat-mini-bar"><div id="s_up_bar" style="width:0%;background:linear-gradient(90deg,#06D6A0,#00B4D8);"></div></div>
      </div>
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon red">⏳</div><span class="stat-mini-delta down" id="s_pend_percent">0%</span></div>
        <div class="stat-mini-value" id="s_pending">0</div>
        <div class="stat-mini-label">待上传照片</div>
        <div class="stat-mini-bar"><div id="s_pend_bar" style="width:0%;background:linear-gradient(90deg,#EF4444,#DC2626);"></div></div>
      </div>
      <!-- 🆕 第7个KPI：💬 用户留言反馈 · 【A3 用户要求】：不再打开所有人混放的总览
           → 点击直接跳到「第一条有未读留言的用户」记录行，在他的详情面板内独立查看该用户自己的留言（单用户独立，不跟别人混放） -->
      <div class="stat-mini" style="cursor:pointer;" onclick="jumpFirstUnreadMsgUser()" title="点击定位到第一条有未读留言的用户，在该用户详情面板独立查看他自己的修图建议（不混放）">
        <div class="stat-mini-head">
          <div class="stat-mini-icon" style="background:linear-gradient(135deg,#FBBF24,#F59E0B);color:#fff;">💬</div>
          <span class="stat-mini-delta up" id="s_msg_unread_label" style="background:rgba(6,214,160,0.16);color:#6EE7B7;border:1px solid rgba(6,214,160,0.32);">暂无反馈</span>
        </div>
        <div class="stat-mini-value" id="s_msg_total">0</div>
        <div class="stat-mini-label">用户留言反馈</div>
        <div class="stat-mini-bar"><div id="s_msg_bar" style="width:0%;background:linear-gradient(90deg,#FBBF24,#EF4444);"></div></div>
      </div>
    </div>

    <!-- 主双栏：左表格 + 右详情面板 -->
    <div class="records-with-detail">
      <!-- 左：筛选+表格 -->
      <section class="records-main">
        <!-- 玻璃工具条 -->
        <div class="toolbar-glass">
          <div class="toolbar-group">
            <div class="field-wrap">
              <select class="select" id="prizeFilter" onchange="renderRecords()">
              <option value="all">🎁 全部奖品等级</option>
              <option value="1">🥇 一等奖（20元红包）</option>
              <option value="2">🧧 二等奖（手办）</option>
              <option value="0">💫 谢谢参与</option>
            </select>
            </div>
            <div class="field-wrap">
              <select class="select" id="photoFilter" onchange="renderRecords()">
              <option value="all">📸 全部照片状态</option>
              <option value="uploaded">✅ 已传照片</option>
              <option value="pending">⏳ 待传照片</option>
            </select>
            </div>
            <div class="field-wrap">
              <input type="text" class="input" id="searchInput" placeholder="搜索COS或微信号..." oninput="renderRecords()">
              <span class="field-icon">🔍</span>
            </div>
          </div>
          <div class="toolbar-group">
            <span style="font-size:12px;color:#64748B;" id="matchInfo">共 0 条</span>
          </div>
        </div>

        <!-- 主表格卡 -->
        <div class="table-wrap">
          <div class="table-wrap-head">
          <div class="table-wrap-title"><span class="dot"></span>参与记录流水</div>
          <div style="display:flex;gap:8px;align-items:center;">
            <span style="font-size:11px;color:#64748B;">当前筛选结果：</span>
            <span class="badge badge-ok" style="padding:4px 10px;"><span class="badge-dot"></span><span id="filteredCount">0</span> 条</span>
          </div>
          </div>
          <div class="table-scroll">
            <table class="admin-table">
              <thead>
                <tr>
                  <th style="width:52px;">#</th>
                  <th>COS 名称</th>
                  <th>微信号</th>
                  <th style="width:138px;">IP 地址</th>
                  <th style="width:100px;">等级</th>
                  <th>奖品</th>
                  <th style="width:170px;">抽奖时间</th>
                  <th style="width:72px;">缩略图</th>
                  <th style="width:108px;">照片</th>
                  <th style="width:112px;">💬 留言</th>
                  <th style="width:290px;">操作</th>
                </tr>
              </thead>
              <tbody id="recordTable"></tbody>
            </table>
            <div class="empty-state" id="emptyState" style="display:none;">
              <div class="emoji">📭</div>
              <p>暂无匹配的抽奖记录</p>
            </div>
          </div>
        </div>
      </section>

      <!-- 右：照片详情面板 -->
      <aside class="detail-panel" id="detailPanel">
        <div class="detail-panel-head">
          <div class="detail-panel-title">🔎 <span>照片详情</span></div>
          <button class="detail-panel-close" id="detailClose" title="关闭" onclick="closeDetail()">✕</button>
        </div>

        <div id="detailEmpty" style="display:block;">
          <div class="detail-photo-box">
            <div class="detail-photo-empty">
              <div class="dpe-emoji">👈</div>
              <div>点击左侧任意一行<br>查看照片与用户详情</div>
            </div>
          </div>
          <div class="detail-info-grid">
            <div class="di-label">COS 名称</div><div class="di-val" style="color:#475569;">—</div>
            <div class="di-label">微信号</div><div class="di-val mono" style="color:#475569;">—</div>
            <div class="di-label">奖品等级</div><div class="di-val" style="color:#475569;">—</div>
            <div class="di-label">抽奖时间</div><div class="di-val" style="color:#475569;">—</div>
          </div>
          <div class="detail-actions">
            <button class="btn btn-ghost" disabled>⬆ 上传照片</button>
          </div>
        </div>

        <div id="detailContent" style="display:none;">
          <div class="detail-photo-box" id="detailPhotoBox" title="点击新窗口打开原图">
            <img id="detailPhotoImg" alt="照片">
          </div>
          <div class="detail-info-grid">
            <div class="di-label">COS 名称</div><div class="di-val" id="dCos">—</div>
            <div class="di-label">微信号</div><div class="di-val mono" id="dWechat">—</div>
            <div class="di-label">IP 地址</div><div class="di-val mono" id="dIp">—</div>
            <div class="di-label">奖品等级</div><div class="di-val" id="dLevel">—</div>
            <div class="di-label">奖品名称</div><div class="di-val" id="dPrize">—</div>
            <div class="di-label">抽奖时间</div><div class="di-val" id="dTime">—</div>
            <div class="di-label">照片状态</div><div class="di-val" id="dStatus">—</div>
          </div>
          <div class="detail-actions" id="dActions"></div>
          <!-- 用户留言 & 摄影师回复面板（端到端链路核心组件） -->
          <div class="msg-panel" id="msgPanel" style="margin-top:16px;">
            <div class="msg-panel-head">
              <div class="msg-panel-title">💬 用户修图建议（留言板）</div>
              <div class="msg-panel-count" id="msgCount">0 条</div>
            </div>
            <div id="msgList" class="msg-list">
              <div class="msg-empty" style="text-align:center;color:#64748B;padding:24px 8px;font-size:12px;">暂无用户建议 —— 用户在前台照片页上传图片后可以在这里给你提修图需求，你回复后会立刻显示在用户前台</div>
            </div>
          </div>
        </div>
      </aside>
    </div>

    <!-- 🆕 💬 留言总览模态框（所有用户建议+回复，一键弹出，最新最上，可直接回复，不用点详情） -->
    <div class="modal-mask" id="allMsgsModal" style="display:none;" onclick="if(event.target===this)closeAllMessagesModal();">
      <div class="modal-box" style="max-width:920px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
          <div>
            <div class="modal-title" style="margin-bottom:2px;">💬 全部用户反馈（留言总览）</div>
            <p class="modal-desc" style="margin:0;font-size:12px;">所有用户发送过来的修图建议 / 留言 —— 按时间倒序，直接回复后立刻显示在用户前台</p>
          </div>
          <button class="detail-panel-close" onclick="closeAllMessagesModal()" title="关闭" style="width:32px;height:32px;border-radius:10px;background:#ffffff;border:1px solid #bae6fd;color:#0284c7;cursor:pointer;font-size:14px;font-weight:700;box-shadow:0 2px 8px rgba(14,165,233,0.06);">✕</button>
        </div>
        <div style="display:flex;gap:14px;align-items:center;margin-bottom:12px;padding:10px 14px;border-radius:12px;background:#f0f9ff;border:1px solid #bae6fd;">
          <span style="font-size:11px;color:#0369a1;font-weight:600;">快速筛选：</span>
          <button class="badge" style="padding:4px 12px;font-size:11px;cursor:pointer;background:#fff7ed;color:#92400e;border:1px solid #fdba74;" onclick="renderAllMessagesModal('unread')">🔴 仅未读 <span id="am_unread">0</span></button>
          <button class="badge" style="padding:4px 12px;font-size:11px;cursor:pointer;background:#e0f2fe;color:#0369a1;border:1px solid #7dd3fc;" onclick="renderAllMessagesModal('unreplied')">⏸ 待回复 <span id="am_unreplied">0</span></button>
          <button class="badge" style="padding:4px 12px;font-size:11px;cursor:pointer;background:#d1fae5;color:#065f46;border:1px solid #6ee7b7;" onclick="renderAllMessagesModal('all')">📋 全部 <span id="am_all">0</span></button>
          <div style="flex:1;"></div>
          <span id="am_status" style="font-size:11px;color:#0369a1;">—</span>
        </div>
        <div id="allMsgsList" style="max-height:66vh;overflow-y:auto;overflow-x:hidden;padding-right:4px;">
          <div style="text-align:center;color:#64748B;padding:40px 8px;font-size:13px;">暂无任何用户反馈 —— 用户在前台照片页上传图片后可给你提修图需求</div>
        </div>
      </div>
    </div>
  </main>

  <!-- ================= 上传照片模态框（青白简洁风 + 已有照片缩略图预览） ================= -->
  <div class="modal-mask" id="uploadModal">
    <div class="modal-box">
      <div class="modal-title">📸 上传照片 · <span id="uploadTargetName" style="color:#0ea5e9;">用户</span></div>
      <p class="modal-desc">按流程操作：① 先点下方白框选图（预览你选的图片）→ ② 调位置号 → ③ 点「确认上传」</p>

      <!-- 【重要】已上传照片概览（9格缩略图，一眼看到自己已经上传了哪些图） -->
      <div class="existing-photos-panel" id="existingPhotosPanel">
        <div class="epp-title">已上传照片（<span id="currentPhotoCount">0</span>/9）· 绿色边框=用户已同意公开（管理员无权删）</div>
        <div class="epp-grid" id="eppGrid"></div>
      </div>

      <!-- 预览你刚选的图（选了才显示，图片一眼可见，纯白底） -->
      <div class="modal-preview" id="uploadPreview">
        <img id="uploadPreviewImg" alt="预览">
        <button type="button" id="removePreviewBtn" onclick="clearPreview()" class="remove-preview-btn" title="移除这张">×</button>
      </div>

      <!-- 选图区（青白大框，一眼能点） -->
      <label class="modal-file-drop" id="dropZone" for="photoFile">
        <div class="drop-icon">🖼️</div>
        <div class="drop-text">点这个白色框 → 选择要上传的图片</div>
        <div class="drop-sub">支持 JPG / PNG / WebP · 最大 25MB · 拖拽也可以</div>
      </label>
      <input type="file" class="modal-file-input" id="photoFile" accept="image/*">

      <!-- 位置序号 + 9格槽（简洁风，青白配色） -->
      <div style="display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:center;margin-bottom:16px;">
        <div>
          <div style="font-size:12px;color:#0369a1;margin-bottom:6px;font-weight:600;">位置序号 1-9</div>
          <div style="display:inline-flex;align-items:center;">
            <button type="button" onclick="spinPosition(-1)"
                    style="width:40px;height:40px;border-radius:10px 0 0 10px;border:1px solid #7dd3fc;background:#ffffff;color:#0369a1;font-size:18px;font-weight:700;cursor:pointer;">−</button>
            <input type="number" id="photoPosition" min="1" max="9" value="1"
                   style="width:58px;height:40px;text-align:center;border-top:1px solid #7dd3fc;border-bottom:1px solid #7dd3fc;border-left:0;border-right:0;background:#f0faff;color:#0c4a6e;font-size:16px;font-weight:700;">
            <button type="button" onclick="spinPosition(1)"
                    style="width:40px;height:40px;border-radius:0 10px 10px 0;border:1px solid #7dd3fc;background:#ffffff;color:#0369a1;font-size:18px;font-weight:700;cursor:pointer;">+</button>
          </div>
        </div>
        <div>
          <div style="font-size:12px;color:#0369a1;margin-bottom:6px;">9 个位置（黄色=当前选中，青底=已占用）</div>
          <div id="positionSlots" style="display:grid;grid-template-columns:repeat(9,1fr);gap:5px;"></div>
        </div>
      </div>

      <!-- 操作按钮（青白主色） -->
      <div class="modal-actions" style="padding-top:2px;display:flex;gap:10px;justify-content:flex-end;">
        <button class="btn btn-ghost" onclick="closeUploadModal()" style="min-width:92px;background:#ffffff;border:1px solid #bae6fd;color:#0c4a6e;">取消</button>
        <button class="btn btn-primary" id="confirmUpload" onclick="confirmUpload()" style="min-width:130px;">⬆ 确认上传</button>
      </div>
    </div>
  </div>

  <script src="/js/admin.js?v=m3"></script>
  <script>
    // 后台所有 <img> 加载失败直接隐藏，避免出现「小图框显示破损图片」的难看现象
    // （包括上传预览、详情预览、列表缩略图、九宫格缩略图）
    (function installImgOnerrorHide() {
      function handleImgError(img) {
        if (!img) return;
        const parent = img.parentElement;
        // 上传预览区域的图片加载失败：只换背景色，不隐藏图片（用户选的data URL不会错）
        if (parent && /modal-preview|detail-photo-box/.test(parent.className || '')) {
          parent.style.background = '#f0f9ff';
          return;
        }
        try { img.style.display = 'none'; } catch (e) {}
        if (!parent) return;
        const pcls = (parent.className || '').toString();
        // 按用户要求：加载失败的缩略图框直接删掉（不留空白占位）
        if (/epp-img-wrap/.test(pcls)) {
          parent.classList.add('img-broken');
          try { parent.style.display = 'none'; } catch (e) {}
          const card = parent.closest ? parent.closest('.epp-card') : null;
          if (card) { try { card.style.display = 'none'; } catch (e) {} }
        }
        // 列表里的 photo-thumb 加载失败：隐藏外框
        if (img.classList.contains('photo-thumb')) {
          const row = img.parentElement;
          if (row) {
            const counter = row.querySelector && row.querySelector('span');
            if (counter) { row.innerHTML = counter.outerHTML; }
            else if (row.parentElement) { row.parentElement.innerHTML = '<span style="color:#334155;font-size:11px;">无</span>'; }
          }
        }
      }
      document.addEventListener('error', function (ev) {
        const t = ev.target;
        if (t && t.tagName === 'IMG') {
          // 上传预览图片（data: URL）出错时不处理，避免用户看不到自己选的图
          const src = t.getAttribute && t.getAttribute('src') || '';
          if (src && src.indexOf('data:') === 0) {
            ev.stopPropagation();
            return;
          }
          handleImgError(t);
        }
      }, true);
      setTimeout(function () {
        document.querySelectorAll('img').forEach(function (img) {
          if (img.complete && img.naturalWidth === 0) {
            const src = img.getAttribute && img.getAttribute('src') || '';
            if (src && src.indexOf('data:') === 0) return;
            handleImgError(img);
          }
        });
      }, 1500);
    })();

    let allRecords = [];
    let currentUploadId = null;
    let selectedId = null;
    let lastFilteredRows = [];

    function loadRecords() {
      fetch('/api/lottery/records')
        .then(r => r.json())
        .then(d => {
          if (d.success) {
            allRecords = d.records || [];
            renderRecords();
            updateStats();
            if (selectedId != null) showDetailById(selectedId, true);
          }
        })
        .catch(() => Admin.showToast('加载失败，请刷新重试', 'err'));
    }

    function updateStats() {
      const total = allRecords.length;
      const p1 = allRecords.filter(r => r.prizeLevel === 1).length;
      const p2 = allRecords.filter(r => r.prizeLevel === 2).length;
      const p3 = allRecords.filter(r => r.prizeLevel === 0 || r.prizeLevel === 3 || r.prizeLevel === 4).length;
      const up = allRecords.filter(r => r.photoUploaded).length;
      const pd = total - up;

      // 🆕 全局留言统计（总用户留言数 + 未读数）
      let msgTotal = 0;
      let msgUnread = 0;
      allRecords.forEach(r => {
        const msgs = Array.isArray(r.messages) ? r.messages : [];
        msgs.forEach(m => {
          if (!m || typeof m !== 'object') return;
          if ((m.by || 'user') !== 'user') return;
          msgTotal += 1;
          if (!m.read) msgUnread += 1;
        });
      });

      document.getElementById('s_total').textContent = Admin.fmtNum(total);
      document.getElementById('s_p1').textContent = Admin.fmtNum(p1);
      document.getElementById('s_p2').textContent = Admin.fmtNum(p2);
      document.getElementById('s_p3').textContent = Admin.fmtNum(p3);
      document.getElementById('s_uploaded').textContent = Admin.fmtNum(up);
      document.getElementById('s_pending').textContent = Admin.fmtNum(pd);

      const pct = v => total === 0 ? '0%' : Math.round(v / total * 100) + '%';
      document.getElementById('s_p1_percent').textContent = pct(p1);
      document.getElementById('s_p2_percent').textContent = pct(p2);
      document.getElementById('s_p3_percent').textContent = pct(p3);
      document.getElementById('s_up_percent').textContent = pct(up);
      document.getElementById('s_pend_percent').textContent = pct(pd);

      const w = v => total === 0 ? '0%' : Math.min(100, Math.round(v / total * 100)) + '%';
      document.getElementById('s_p1_bar').style.width = w(p1);
      document.getElementById('s_p2_bar').style.width = w(p2);
      document.getElementById('s_p3_bar').style.width = w(p3);
      document.getElementById('s_up_bar').style.width = w(up);
      document.getElementById('s_pend_bar').style.width = w(pd);

      // 🆕 渲染 💬 留言KPI卡（s_msg_total / s_msg_unread_label / s_msg_bar）
      const $smt = document.getElementById('s_msg_total');
      if ($smt) $smt.textContent = Admin.fmtNum(msgTotal);
      const $smul = document.getElementById('s_msg_unread_label');
      if ($smul) {
        if (msgTotal === 0) {
          $smul.textContent = '暂无反馈';
          $smul.style.background = 'rgba(6,214,160,0.16)';
          $smul.style.color = '#6EE7B7';
          $smul.style.borderColor = 'rgba(6,214,160,0.32)';
          $smul.style.animation = 'none';
        } else if (msgUnread > 0) {
          $smul.textContent = '未读 ' + msgUnread;
          $smul.style.background = 'rgba(239,68,68,0.18)';
          $smul.style.color = '#FCA5A5';
          $smul.style.borderColor = 'rgba(239,68,68,0.4)';
          $smul.style.animation = 'pulse 1.6s ease-in-out infinite';
        } else {
          $smul.textContent = '全部已读 · ' + msgTotal + '条';
          $smul.style.background = 'rgba(251,191,36,0.14)';
          $smul.style.color = '#FDE68A';
          $smul.style.borderColor = 'rgba(251,191,36,0.32)';
          $smul.style.animation = 'none';
        }
      }
      const $smb = document.getElementById('s_msg_bar');
      if ($smb) $smb.style.width = (total === 0 ? '0%' : Math.min(100, Math.round(msgTotal / Math.max(1, total) * 100)) + '%');
    }

    function prizeBadge(lv) {
      const cls = 'prize' + (lv === 1 ? 1 : lv === 2 ? 2 : lv === 3 ? 3 : 4);
      const txt = lv === 1 ? '一等奖' : lv === 2 ? '二等奖' : lv === 3 ? '三等奖' : '谢谢参与';
      return '<span class="badge badge-' + cls + '"><span class="badge-dot"></span>' + txt + '</span>';
    }

    // ============================================================
    // B3【用户要求】：渲染卡片行 + 右侧⬇展开箭头（点击卡片向下延伸展开完整详情）
    //   · 不再集中显示未读/已读，而是每人卡片下面独立带自己的修图建议留言板 + 照片九宫格 + 回复输入框
    //   · 抽 renderUserMessagesPanel 函数为可复用（既给展开区用，也给旧详情面板用）
    // ============================================================
    function renderUserMessagesPanel(r, forInlineExpand) {
      const rawMsgs = Array.isArray(r.messages) ? r.messages : [];
      const msgs = rawMsgs.filter(m => m && typeof m === 'object');
      const head = (forInlineExpand
        ? '<div class="msg-panel-head" style="padding:10px 14px;background:linear-gradient(135deg,#e0f2fe,#ffffff);border-radius:14px 14px 0 0;border:1px solid #bae6fd;">' +
            '<div class="msg-panel-title" style="font-size:14px;font-weight:700;color:#0c4a6e;">💬 ' + Admin.esc(r.cosName) + ' 的修图建议（留言板）</div>' +
            '<div class="msg-panel-count" style="font-size:11px;color:#0369a1;margin-top:4px;">共 ' + msgs.length + ' 条 · 直接在下面回复，用户前台立刻显示</div>' +
          '</div>'
        : '');
      if (msgs.length === 0) {
        return head +
          '<div class="msg-list" style="padding:20px 12px;background:#ffffff;border:1px solid #bae6fd;border-top:0;border-radius:0 0 14px 14px;">' +
            '<div class="msg-empty" style="text-align:center;color:#0369a1;font-size:12px;">暂无用户建议 —— 用户在前台照片页上传图片后可以在这里提修图需求，你回复后会立刻显示在用户前台</div>' +
          '</div>';
      }
      return head +
        '<div class="msg-list" style="padding:14px;background:#ffffff;border:1px solid #bae6fd;border-top:0;border-radius:0 0 14px 14px;max-height:none;">' +
          msgs.map(m => {
            const mid = Number(m.id || 0);
            const createdAt = Admin.esc(m.createdAt || '');
            const byWho = (m.by || 'user') === 'photographer' ? '📷 摄影师 留言' : '✨ ' + Admin.esc(m.cosName || '用户') + ' 的建议';
            const text = Admin.esc(m.text || '');
            const hasReply = !!(m.reply && String(m.reply).trim());
            const replyText = hasReply ? Admin.esc(String(m.reply)) : '';
            const replyAt = hasReply ? Admin.esc(m.replyAt || '') : '';
            const unreadCls = !m.read && (m.by || 'user') === 'user' ? 'msg-item-unread' : '';
            return `
              <div class="msg-item ${unreadCls}" data-msg-id="${mid}" data-record-id="${r.id}" style="margin-bottom:14px;">
                <div class="msg-head">
                  <div class="msg-by">${byWho}</div>
                  ${createdAt ? `<div class="msg-time">${createdAt}</div>` : ''}
                </div>
                <div class="msg-text" style="line-height:1.65;">${text}</div>
                ${hasReply ? `
                  <div class="msg-reply">
                    <div class="msg-reply-head">
                      <span class="msg-by">📷 我的回复</span>
                      ${replyAt ? `<span class="msg-time">${replyAt}</span>` : ''}
                    </div>
                    <p class="msg-reply-text">${replyText}</p>
                  </div>
                ` : `
                  <div class="msg-reply-form">
                    <textarea class="msg-reply-input" placeholder="告诉用户：修图完成了 / 需要什么素材 / 预计多久出图..." rows="2"></textarea>
                    <div class="msg-reply-actions">
                      <button class="btn btn-sm btn-ghost msg-reply-skip" data-msg-id="${mid}" data-record-id="${r.id}" title="标记为已读不回复">📖 已读</button>
                      <button class="btn btn-sm btn-green msg-reply-submit" data-msg-id="${mid}" data-record-id="${r.id}">📮 发送回复给用户</button>
                    </div>
                  </div>
                `}
              </div>
            `;
          }).join('') +
        '</div>';
    }
    function renderUserPhotosPanelInline(r) {
      const photos = Array.isArray(r.photos) ? r.photos : [];
      const photoCount = photos.length;
      const approvedCount = photos.filter(p => p.publicApproved).length;
      if (photoCount === 0) {
        return '<div style="padding:16px 14px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:14px;margin-bottom:14px;color:#0369a1;font-size:12px;">📷 该用户还未上传照片 · 可点右侧「⬆ 上传照片」传图</div>';
      }
      const sorted = [...photos].sort((a,b) => (Number(a.photoPosition)||999)-(Number(b.photoPosition)||999));
      const gridHtml = sorted.map(p => `
        <div style="position:relative;aspect-ratio:1;border-radius:12px;overflow:hidden;border:3px solid ${p.publicApproved ? '#10b981' : '#7dd3fc'};">
          <img src="${Admin.esc(p.photoUrl)}" loading="lazy" referrerpolicy="no-referrer" style="width:100%;height:100%;object-fit:cover;cursor:pointer;display:block;" data-open-url="${Admin.esc(p.photoUrl)}" alt="位置 #${p.photoPosition}${p.publicApproved?' · ✅已公开':''}" title="位置 #${p.photoPosition}${p.publicApproved?' · ✅用户已同意公开':''}">
          <div style="position:absolute;top:6px;left:6px;padding:3px 8px;border-radius:8px;background:rgba(255,255,255,0.95);color:#0369a1;font-size:11px;font-weight:700;border:1px solid #bae6fd;box-shadow:0 2px 8px rgba(14,165,233,0.1);">
            #${Admin.esc(String(p.photoPosition||'?'))}${p.publicApproved ? ' ✅' : ''}
          </div>
          ${p.uploadedAt ? `<div style="position:absolute;bottom:6px;right:6px;padding:2px 6px;border-radius:6px;background:rgba(255,255,255,0.95);color:#0369a1;font-size:10px;border:1px solid #bae6fd;">${Admin.esc(String(p.uploadedAt).slice(5,16)||'')}</div>` : ''}
        </div>
      `).join('');
      // 九宫格：9 格 grid，空位用占位符填充
      let slotsHtml = '';
      for (let s = 1; s <= 9; s++) {
        const found = sorted.find(p => Number(p.photoPosition) === s);
        if (found) continue;
        slotsHtml += `<div style="aspect-ratio:1;border-radius:12px;border:2px dashed #bae6fd;background:#f8fafc;display:flex;align-items:center;justify-content:center;color:#0284c7;font-size:12px;font-weight:600;">#${s} 空位</div>`;
      }
      return `
        <div style="padding:14px;background:#ffffff;border:1px solid #bae6fd;border-radius:14px;margin-bottom:14px;box-shadow:0 4px 16px rgba(14,165,233,0.05);">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
            <div style="font-size:14px;font-weight:700;color:#0c4a6e;">📷 ${Admin.esc(r.cosName)} 的照片九宫格 · ${photoCount}/9</div>
            <div style="font-size:11px;color:#0369a1;">✅ 用户已同意公开 ${approvedCount} 张</div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(9,1fr);gap:8px;">${gridHtml + slotsHtml}</div>
        </div>
      `;
    }

    function renderRecords() {
      const tbody = document.getElementById('recordTable');
      const empty = document.getElementById('emptyState');
      const pf = document.getElementById('prizeFilter').value;
      const phf = document.getElementById('photoFilter').value;
      const kw = (document.getElementById('searchInput').value || '').trim().toLowerCase();

      let rows = allRecords;
      if (pf !== 'all') rows = rows.filter(r => String(r.prizeLevel) === String(pf));
      if (phf === 'uploaded') rows = rows.filter(r => r.photoUploaded);
      else if (phf === 'pending') rows = rows.filter(r => !r.photoUploaded);
      if (kw) rows = rows.filter(r => (r.cosName || '').toLowerCase().includes(kw) || (r.wechatId || '').toLowerCase().includes(kw));
      lastFilteredRows = rows;

      document.getElementById('filteredCount').textContent = Admin.fmtNum(rows.length);
      const mi = document.getElementById('matchInfo');
      if (mi) mi.textContent = '共 ' + Admin.fmtNum(allRecords.length) + ' 条 · 匹配 ' + Admin.fmtNum(rows.length) + ' 条';

      if (rows.length === 0) { tbody.innerHTML = ''; empty.style.display = 'block'; return; }
      empty.style.display = 'none';

      tbody.innerHTML = rows.map((r, i) => {
        // 重置抽奖按钮（所有记录都有）
        let resetBtn = '<button class="row-btn btn-reset" data-reset-id="' + r.id + '" title="删除这条记录并清空该IP当日次数，让用户可重新抽奖">🔄 重置抽奖</button>';
        let photoBtn = '';
        const photos = Array.isArray(r.photos) ? r.photos : [];
        const approvedCount = photos.filter(p => p.publicApproved).length;
        const photoCount = photos.length;
        const firstPhoto = photoCount > 0
          ? photos.reduce((a,b) => (Number(a.photoPosition)||999) < (Number(b.photoPosition)||999) ? a : b)
          : null;

        if (photoCount > 0) {
          photoBtn =
            (firstPhoto ? '<button class="row-btn btn-view" data-open-url="' + Admin.esc(firstPhoto.photoUrl) + '" title="新窗口打开第1张原图">🔍 查看</button>' : '') +
            '<button class="row-btn btn-upl" data-id="' + r.id + '" data-name="' + Admin.esc(r.cosName) + '">⬆ 追加/替换</button>' +
            (photoCount > 0 && approvedCount === 0
              ? '<button class="row-btn btn-del" data-revoke-id="' + r.id + '">🗑 全部撤回</button>'
              : '');
        } else {
          photoBtn = '<button class="row-btn btn-upl" data-id="' + r.id + '" data-name="' + Admin.esc(r.cosName) + '">⬆ 上传照片</button>';
        }
        const action = resetBtn + photoBtn;
        const thumb = (firstPhoto
          ? '<div style="display:flex;align-items:center;gap:6px;">' +
              '<img src="' + firstPhoto.photoUrl.replace('/data/photos/', '/data/thumb/') + '" class="photo-thumb" style="width:48px;height:48px;border-radius:12px;cursor:pointer;" data-open-url="' + Admin.esc(firstPhoto.photoUrl) + '" alt="thumb">' +
              '<span style="font-size:11px;color:#94A3B8;">' + photoCount + '张' + (approvedCount>0?'<br>✅'+approvedCount:'') + '</span>' +
            '</div>'
          : '<span style="color:#334155;font-size:11px;">无</span>');
        const statusBadge = photoCount === 0
          ? '<span class="badge badge-warn"><span class="badge-dot"></span>待上传</span>'
          : approvedCount === photoCount
            ? '<span class="badge badge-ok"><span class="badge-dot"></span>已公开' + approvedCount + '</span>'
            : approvedCount === 0
              ? '<span class="badge badge-warn"><span class="badge-dot"></span>' + photoCount + '张·待同意</span>'
              : '<span class="badge badge-ok2"><span class="badge-dot"></span>' + approvedCount + '/' + photoCount + '公开</span>';
        const selClass = (selectedId === r.id) ? ' selected' : '';

        // B3【用户要求】💬 留言列：简洁显示 总条数 / 未读，不再搞集中弹窗！
        const rawMsgs2 = Array.isArray(r.messages) ? r.messages : [];
        const userMsgs2 = rawMsgs2.filter(m => m && typeof m === 'object' && (m.by || 'user') === 'user');
        const msgUnreadCount2 = userMsgs2.filter(m => !m.read).length;
        const photographerMsgs2 = rawMsgs2.filter(m => m && typeof m === 'object' && (m.by || 'user') === 'photographer');
        const allMsgCount2 = rawMsgs2.filter(m => m && typeof m === 'object').length;
        let msgCellHtml = '';
        if (allMsgCount2 === 0) {
          msgCellHtml = '<span style="color:#334155;font-size:11px;">无</span>';
        } else {
          let badgeCss2 = 'background:rgba(6,214,160,0.14);color:#6EE7B7;border-color:rgba(6,214,160,0.32);';
          if (msgUnreadCount2 > 0) {
            badgeCss2 = 'background:rgba(239,68,68,0.16);color:#FCA5A5;border-color:rgba(239,68,68,0.4);box-shadow:0 0 0 3px rgba(239,68,68,0.08);animation:pulse 1.6s ease-in-out infinite;';
          } else if (userMsgs2.length > 0) {
            badgeCss2 = 'background:rgba(251,191,36,0.14);color:#FDE68A;border-color:rgba(251,191,36,0.32);';
          }
          const badgeText2 = msgUnreadCount2 > 0
            ? '未读 ' + msgUnreadCount2
            : (photographerMsgs2.length > 0 ? '已回复 ' + userMsgs2.length : userMsgs2.length + ' 条');
          // B3：点💬不弹窗 → 直接展开该行的⬇箭头
          msgCellHtml =
            '<button class="badge" style="' + badgeCss2 + 'padding:3px 9px;font-size:11px;font-weight:600;border:1px solid;cursor:pointer;" ' +
              'title="点击展开这条卡片，查看『' + Admin.esc(r.cosName || '未知用户') + '』完整的修图建议和照片九宫格" ' +
              'onclick="event.stopPropagation();toggleExpandRowById(' + r.id + ');">💬 ' + Admin.esc(badgeText2) + '</button>';
        }

        // B3【用户要求】：右侧「⬇ 向下箭头」按钮 —— 点击后卡片向下延伸展开（不是弹窗！）
        const expandBtn =
          '<button type="button" class="row-expand-btn" data-expand-id="' + r.id + '" ' +
            'title="向下展开：查看该用户完整的照片九宫格 + 修图建议留言板（每人独立一条，不再集中混放）" ' +
            'onclick="event.stopPropagation();toggleExpandRowById(' + r.id + ');" ' +
            'style="width:36px;height:36px;border-radius:10px;border:1px solid #bae6fd;background:#ffffff;color:#0284c7;cursor:pointer;font-size:18px;font-weight:800;display:inline-flex;align-items:center;justify-content:center;transition:all .18s ease;box-shadow:0 2px 8px rgba(14,165,233,0.06);" ' +
            'aria-label="展开详情">⬇</button>';

        // B3：主卡片行（第 1 行） + 可选展开行（第 2 行，默认 hidden；展开后显示：照片九宫格 + 修图建议留言板）
        const expandTd =
          '<td colspan="13" style="padding:14px 16px 20px;background:#f0f9ff;border-top:1px solid #bae6fd;">' +
            renderUserPhotosPanelInline(r) +
            renderUserMessagesPanel(r, true) +
          '</td>';

        const isOpen = expandedIds.has(r.id);
        const rowExpandDisplay = isOpen ? 'table-row' : 'none';
        const expandBtnText = isOpen ? '⬆' : '⬇';
        const expandBtnTitle = isOpen ? '收起详情' : '向下展开：查看该用户完整的照片九宫格 + 修图建议留言板（每人独立一条，不再集中混放）';
        // B3：右侧「⬇ 向下箭头」按钮（展开态保持按钮状态与 expandedIds 一致）
        const expandBtnSafe =
          '<button type="button" class="row-expand-btn" data-expand-id="' + r.id + '" ' +
            'title="' + expandBtnTitle + '" ' +
            'onclick="event.stopPropagation();toggleExpandRowById(' + r.id + ');" ' +
            'style="width:36px;height:36px;border-radius:10px;border:1px solid #bae6fd;background:#ffffff;color:#0284c7;cursor:pointer;font-size:18px;font-weight:800;display:inline-flex;align-items:center;justify-content:center;transition:all .18s ease;box-shadow:0 2px 8px rgba(14,165,233,0.06);" ' +
            'aria-label="展开详情">' + expandBtnText + '</button>';

        return '<tr class="row' + selClass + '" data-id="' + r.id + '" data-mainrow="1" style="cursor:pointer;">' +
          '<td data-label="#" style="color:#64748B;width:52px;">' + (i + 1) + '</td>' +
          '<td data-label="COS名称" style="color:#0c4a6e;font-weight:600;">' + Admin.esc(r.cosName) + '</td>' +
          '<td data-label="微信号" class="mono">' + Admin.esc(r.wechatId) + '</td>' +
          '<td data-label="IP" class="mono" style="color:#64748B;">' + Admin.esc(r.ip || '-') + '</td>' +
          '<td data-label="等级">' + prizeBadge(r.prizeLevel) + '</td>' +
          '<td data-label="奖品">' + Admin.esc(r.prizeName || '-') + '</td>' +
          '<td data-label="时间" style="color:#64748B;">' + Admin.esc(r.timeStr || '-') + '</td>' +
          '<td data-label="缩略图">' + thumb + '</td>' +
          '<td data-label="状态">' + statusBadge + '</td>' +
          '<td data-label="留言">' + msgCellHtml + '</td>' +
          '<td data-label="操作">' + action + '</td>' +
          '<td data-label="展开" style="width:56px;text-align:center;">' + expandBtnSafe + '</td>' +
          '</tr>' +
          '<tr class="row-expand" data-expand-for="' + r.id + '" style="display:' + rowExpandDisplay + ';">' + expandTd + '</tr>';
      }).join('');
      // 渲染后：如果有滚动定位需求，保持 selectedId 不变
    }

    // B3：切换 ⬇ 展开 / 收起（每人卡片向下延伸展开自己的详情）
    // 【性能+防闪退修复】：展开态集中存 expandedIds，渲染时自动应用
    const expandedIds = new Set();
    function toggleExpandRowById(id) {
      if (id == null) return;
      const numeric = Number(id);
      const exRow = document.querySelector('#recordTable tr.row-expand[data-expand-for="' + numeric + '"]');
      const btn = document.querySelector('#recordTable button.row-expand-btn[data-expand-id="' + numeric + '"]');
      if (!exRow) return;
      const isOpen = expandedIds.has(numeric);
      if (isOpen) {
        expandedIds.delete(numeric);
        exRow.style.display = 'none';
        if (btn) { btn.textContent = '⬇'; btn.title = '向下展开：查看该用户完整的照片九宫格 + 修图建议留言板'; }
      } else {
        expandedIds.add(numeric);
        exRow.style.display = 'table-row';
        if (btn) { btn.textContent = '⬆'; btn.title = '收起详情'; }
        try {
          const mainRow = document.querySelector('#recordTable tr.row[data-id="' + numeric + '"]');
          if (mainRow) mainRow.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (e) {}
        const r = allRecords.find(x => x.id === numeric);
        if (r && Array.isArray(r.messages)) {
          const unreadIds = [];
          r.messages.forEach(m => {
            if (m && typeof m === 'object' && !m.read && (m.by || 'user') === 'user') {
              m.read = true;
              if (m.id) unreadIds.push(Number(m.id));
            }
          });
          unreadIds.forEach(mid => {
            fetch('/api/admin/message/' + numeric + '/' + mid + '/read', { method: 'POST' })
              .then(() => { try { if (typeof updateStats === 'function') updateStats(); } catch(e) {} })
              .catch(() => {});
          });
          if (unreadIds.length > 0 && typeof renderRecords === 'function') {
            // 不再用 setTimeout(renderRecords) 触发重绘，否则会把刚展开/正在输入的表单冲掉
            if (typeof updateStats === 'function') updateStats();
          }
        }
      }
    }

    // ========== 右侧详情面板 ==========
    function showDetailById(id, silent) {
      const r = allRecords.find(x => x.id === id);
      if (!r) { closeDetail(); return; }
      selectedId = id;
      // 高亮对应行
      document.querySelectorAll('#recordTable tr.row').forEach(tr => {
        tr.classList.toggle('selected', Number(tr.getAttribute('data-id')) === id);
      });

      const prizeLabel = r.prizeLevel === 1 ? '一等奖' : r.prizeLevel === 2 ? '二等奖' : '谢谢参与';
      const badgeCls = r.prizeLevel === 1 ? 'badge-prize1' : r.prizeLevel === 2 ? 'badge-prize2' : r.prizeLevel === 3 ? 'badge-prize3' : 'badge-prize4';

      document.getElementById('detailEmpty').style.display = 'none';
      document.getElementById('detailContent').style.display = 'block';
      document.getElementById('dCos').textContent = r.cosName || '—';
      document.getElementById('dWechat').textContent = r.wechatId || '—';
      document.getElementById('dIp').textContent = r.ip || '-';
      document.getElementById('dLevel').innerHTML = '<span class="badge ' + badgeCls + '"><span class="badge-dot"></span>' + prizeLabel + '</span>';
      document.getElementById('dPrize').textContent = r.prizeName || '—';
      document.getElementById('dTime').textContent = r.timeStr || '—';

      const photoBox = document.getElementById('detailPhotoBox');
      const photoImg = document.getElementById('detailPhotoImg');
      const statusEl = document.getElementById('dStatus');
      const actionsEl = document.getElementById('dActions');

      const photos = Array.isArray(r.photos) ? r.photos : [];
      const photoCount = photos.length;
      const approvedCount = photos.filter(p => p.publicApproved).length;
      const firstPhoto = photoCount > 0
        ? photos.reduce((a,b) => (Number(a.photoPosition)||999) < (Number(b.photoPosition)||999) ? a : b)
        : null;

      let statusBadge = '';
      if (photoCount === 0) {
        statusBadge = '<span class="badge badge-warn"><span class="badge-dot"></span>待上传</span>';
      } else if (approvedCount === photoCount) {
        statusBadge = '<span class="badge badge-ok"><span class="badge-dot"></span>✅ 已公开' + approvedCount + '/' + photoCount + '</span>';
      } else if (approvedCount === 0) {
        statusBadge = '<span class="badge badge-warn"><span class="badge-dot"></span>' + photoCount + '张·等待用户同意</span>';
      } else {
        statusBadge = '<span class="badge badge-ok2"><span class="badge-dot"></span>部分公开 ' + approvedCount + '/' + photoCount + '</span>';
      }
      statusEl.innerHTML = statusBadge;

      if (firstPhoto) {
        photoImg.src = firstPhoto.photoUrl;
        photoBox.setAttribute('data-open-url', firstPhoto.photoUrl);
        photoBox.style.cursor = 'pointer';
        // 清理旧的grid占位
        photoBox.querySelectorAll('.detail-photo-grid').forEach(g => g.remove());
        photoBox.querySelectorAll('.detail-photo-empty').forEach(g => g.remove());
        // 如果有多张：在photoBox内追加一个小网格
        if (photoCount > 1) {
          const sorted = [...photos].sort((a,b) => (Number(a.photoPosition)||999)-(Number(b.photoPosition)||999));
          const grid = document.createElement('div');
          grid.className = 'detail-photo-grid';
          grid.style.marginTop = '10px';
          grid.style.display = 'grid';
          grid.style.gridTemplateColumns = 'repeat(9, 1fr)';
          grid.style.gap = '4px';
          grid.innerHTML = sorted.map(p => `
            <div style="aspect-ratio:1;border-radius:6px;overflow:hidden;border:2px solid ${p.publicApproved ? 'rgba(6,214,160,0.5)' : 'rgba(0,180,216,0.4)'};">
              <img src="${Admin.esc(p.photoUrl.replace('/data/photos/', '/data/thumb/'))}" class="photo-thumb" style="width:100%;height:100%;object-fit:cover;cursor:pointer;" data-open-url="${Admin.esc(p.photoUrl)}" alt="#${p.photoPosition}" loading="lazy" referrerpolicy="no-referrer" title="位置 #${p.photoPosition}${p.publicApproved?' · ✅已公开':''}">
            </div>
          `).join('');
          photoBox.appendChild(grid);
        }
      } else {
        photoImg.removeAttribute('src');
        photoBox.innerHTML = '<div class="detail-photo-empty"><div class="dpe-emoji">📷</div><div>暂无照片<br>点击下方按钮上传</div></div>';
        photoBox.removeAttribute('data-open-url');
        photoBox.style.cursor = '';
      }

      // 操作按钮
      let actionsHtml =
        '<button class="btn btn-orange" onclick="resetLotteryById(' + r.id + ')" title="删除该记录 + 清除该IP当日次数，让该用户可重新抽奖">🔄 重置抽奖机会</button>';
      if (firstPhoto) {
        // 检查是否有用户自己上传的照片
        const hasUserUploaded = Array.isArray(photos) && photos.some(p => p.uploadedBy === 'user');
        actionsHtml +=
          '<button class="btn btn-primary" data-open-url="' + Admin.esc(firstPhoto.photoUrl) + '">🔍 新窗口查看首图</button>' +
          '<button class="btn btn-green" onclick="openUploadModal(' + r.id + ', ' + JSON.stringify(r.cosName || '未知用户') + ')">⬆ 追加/替换照片</button>';
        // 只有当没有任何一张被用户同意公开 且 没有用户上传的照片时，管理员才能"全部撤回"
        if (approvedCount === 0 && photoCount > 0 && !hasUserUploaded) {
          actionsHtml +=
            '<button class="btn btn-red" onclick="revokePhotoById(' + r.id + ')">🗑 撤回全部照片（删文件）</button>';
        } else if (approvedCount > 0) {
          actionsHtml +=
            '<button class="btn btn-red" title="' + approvedCount + '张已由用户同意公开，管理员无权撤回" disabled style="opacity:0.6;cursor:not-allowed;">🔒 ' + approvedCount + '张已公开·不可撤回</button>';
        } else if (hasUserUploaded) {
          actionsHtml +=
            '<button class="btn btn-red" title="包含用户自己上传的照片，管理员无权删除" disabled style="opacity:0.6;cursor:not-allowed;">🔒 用户上传·不可删除</button>';
        }
      } else {
        actionsHtml +=
          '<button class="btn btn-green" onclick="openUploadModal(' + r.id + ', ' + JSON.stringify(r.cosName || '未知用户') + ')">⬆ 上传照片</button>';
      }
      actionsEl.innerHTML = actionsHtml;

      // === 渲染用户留言板（端到端反馈链路：用户→后台管理员→回显用户） ===
      const msgListEl = document.getElementById('msgList');
      const msgCountEl = document.getElementById('msgCount');
      const msgPanelEl = document.getElementById('msgPanel');
      const rawMsgs = Array.isArray(r.messages) ? r.messages : [];
      const msgs = rawMsgs.filter(m => m && typeof m === 'object');
      if (msgCountEl) msgCountEl.textContent = msgs.length + ' 条';
      if (!msgListEl) {
        // noop
      } else if (msgs.length === 0) {
        msgListEl.innerHTML = '<div class="msg-empty" style="text-align:center;color:#64748B;padding:24px 8px;font-size:12px;">暂无用户建议 —— 用户在前台照片页上传图片后可以在这里给你提修图需求，你回复后会立刻显示在用户前台</div>';
      } else {
        msgListEl.innerHTML = msgs.map(m => {
          const mid = Number(m.id || 0);
          const createdAt = Admin.esc(m.createdAt || '');
          const byWho = (m.by || 'user') === 'photographer' ? '📷 摄影师 留言' : '✨ ' + Admin.esc(m.cosName || '用户') + ' 的建议';
          const text = Admin.esc(m.text || '');
          const hasReply = !!(m.reply && String(m.reply).trim());
          const replyText = hasReply ? Admin.esc(String(m.reply)) : '';
          const replyAt = hasReply ? Admin.esc(m.replyAt || '') : '';
          const unreadCls = !m.read && (m.by || 'user') === 'user' ? 'msg-item-unread' : '';
          return `
            <div class="msg-item ${unreadCls}" data-msg-id="${mid}" data-record-id="${r.id}">
              <div class="msg-head">
                <div class="msg-by">${byWho}</div>
                ${createdAt ? `<div class="msg-time">${createdAt}</div>` : ''}
              </div>
              <div class="msg-text">${text}</div>
              ${hasReply ? `
                <div class="msg-reply">
                  <div class="msg-reply-head">
                    <span class="msg-by">📷 我的回复</span>
                    ${replyAt ? `<span class="msg-time">${replyAt}</span>` : ''}
                  </div>
                  <p class="msg-reply-text">${replyText}</p>
                </div>
              ` : `
                <div class="msg-reply-form">
                  <textarea class="msg-reply-input" placeholder="告诉用户：修图完成了 / 需要什么素材 / 预计多久出图..." rows="2"></textarea>
                  <div class="msg-reply-actions">
                    <button class="btn btn-sm btn-ghost msg-reply-skip" data-msg-id="${mid}" data-record-id="${r.id}" title="标记为已读不回复">📖 已读</button>
                    <button class="btn btn-sm btn-green msg-reply-submit" data-msg-id="${mid}" data-record-id="${r.id}">📮 发送回复给用户</button>
                  </div>
                </div>
              `}
            </div>
          `;
        }).join('');
      }
      // 自动标记：当前详情面板的未读用户留言 —— 先在本地状态标记为 read，再 POST /read 接口写回服务器（防止刷新后仍显示"未读"）
      if (msgs.length > 0 && Array.isArray(r.messages)) {
        const unreadUserMsgIds = [];
        r.messages.forEach(m => {
          if (m && typeof m === 'object' && !m.read && (m.by || 'user') === 'user') {
            m.read = true;
            if (m.id) unreadUserMsgIds.push(Number(m.id));
          }
        });
        // 批量 POST /read 写回服务器（后台端记录已读时间）
        unreadUserMsgIds.forEach(mid => {
          fetch('/api/admin/message/' + r.id + '/' + mid + '/read', { method: 'POST' })
            .then(rr => rr.json()).catch(() => {});
        });
      }
      // 🆕：如果该记录有未读留言（或筛选过的任意留言），自动把详情面板滚动到最上面（留言板被 order:-1 放在第一个）
      const hasAnyMessage = msgs.length > 0;
      if (hasAnyMessage) {
        setTimeout(focusMsgPanel, 60);
      }
    }

    // ========== 用户留言板：事件委托（已读+回复） ==========
    document.addEventListener('click', e => {
      if (!e.target) return;
      // 发送回复
      const submitBtn = e.target.closest && e.target.closest('.msg-reply-submit');
      if (submitBtn) {
        const rid = parseInt(submitBtn.getAttribute('data-record-id'), 10);
        const mid = parseInt(submitBtn.getAttribute('data-msg-id'), 10);
        if (Number.isNaN(rid) || Number.isNaN(mid)) return;
        const item = submitBtn.closest && submitBtn.closest('.msg-item');
        const ta = item ? item.querySelector('.msg-reply-input') : null;
        const text = ta ? (ta.value || '').trim() : '';
        if (!text) { Admin.showToast('请填写回复内容', 'err'); return; }
        submitBtn.disabled = true; submitBtn.textContent = '发送中...';
        fetch('/api/admin/message/' + rid + '/' + mid + '/reply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reply: text })
        }).then(r => r.json()).then(d => {
          if (d.success) {
            Admin.showToast('✅ 回复已发送，用户前台立即可见');
            // 同步更新内存 allRecords 中的 messages
            const tgt = allRecords.find(x => x.id === rid);
            if (tgt && Array.isArray(tgt.messages) && d.updatedMessage) {
              const idx = tgt.messages.findIndex(m => m && typeof m === 'object' && Number(m.id) === Number(d.updatedMessage.id));
              if (idx >= 0) tgt.messages[idx] = d.updatedMessage;
            }
            if (selectedId != null) showDetailById(selectedId, true);
          } else {
            Admin.showToast('回复失败：' + (d.message || ''), 'err');
            submitBtn.disabled = false; submitBtn.textContent = '📮 发送回复给用户';
          }
        }).catch(() => {
          Admin.showToast('网络错误，请稍后重试', 'err');
          submitBtn.disabled = false; submitBtn.textContent = '📮 发送回复给用户';
        });
        return;
      }
      // 仅标记已读
      const skipBtn = e.target.closest && e.target.closest('.msg-reply-skip');
      if (skipBtn) {
        const rid = parseInt(skipBtn.getAttribute('data-record-id'), 10);
        const mid = parseInt(skipBtn.getAttribute('data-msg-id'), 10);
        if (Number.isNaN(rid) || Number.isNaN(mid)) return;
        skipBtn.disabled = true;
        fetch('/api/admin/message/' + rid + '/' + mid + '/read', { method: 'POST' })
          .then(r => r.json()).catch(() => ({ success: false }))
          .then(() => {
            const tgt = allRecords.find(x => x.id === rid);
            if (tgt && Array.isArray(tgt.messages)) {
              tgt.messages.forEach(m => { if (m && typeof m === 'object' && Number(m.id) === mid) m.read = true; });
            }
            if (selectedId != null) showDetailById(selectedId, true);
          });
        return;
      }
    });

    function closeDetail() {
      selectedId = null;
      document.querySelectorAll('#recordTable tr.row').forEach(tr => tr.classList.remove('selected'));
      document.getElementById('detailEmpty').style.display = 'block';
      document.getElementById('detailContent').style.display = 'none';
    }

    // 🆕 焦点定位到详情面板最上面（msgPanel留言板，order:-1 让它在最上面）
    function focusMsgPanel() {
      try {
        const panel = document.getElementById('detailPanel');
        if (panel) panel.scrollTo({ top: 0, behavior: 'smooth' });
        const mp = document.getElementById('msgPanel');
        if (mp) {
          mp.animate && mp.animate([{ boxShadow:'0 0 0 0 rgba(251,191,36,0.0)' }, { boxShadow:'0 0 0 8px rgba(251,191,36,0.22)' }, { boxShadow:'0 0 0 0 rgba(251,191,36,0)' }], { duration: 1400 });
        }
      } catch(e) {}
    }

    // 🆕 打开「全部用户反馈（留言总览）」模态框 —— 用户再也不用一个个点详情找了
    function openAllMessagesModal() {
      const m = document.getElementById('allMsgsModal');
      if (m) m.style.display = 'flex';
      renderAllMessagesModal('all');
    }
    function closeAllMessagesModal() {
      const m = document.getElementById('allMsgsModal');
      if (m) m.style.display = 'none';
      // 关闭后刷新数据（如果有回复、有标已读）+ 刷新列表列的留言徽标
      loadAll();
    }
    // 渲染所有留言（按时间倒序，支持筛选）
    let _amLastFilter = 'all';
    function renderAllMessagesModal(filterKey) {
      if (typeof filterKey === 'string') _amLastFilter = filterKey;
      const listEl = document.getElementById('allMsgsList');
      const amAll = document.getElementById('am_all');
      const amUnread = document.getElementById('am_unread');
      const amUnreplied = document.getElementById('am_unreplied');
      const amStatus = document.getElementById('am_status');
      if (!listEl) return;

      // 扁平化所有用户留言（只按 by==user 来，摄影师的不作为主条目显示，而是作为 reply 显示）
      const flat = [];
      let totalAll = 0, totalUnread = 0, totalUnreplied = 0;
      allRecords.forEach(r => {
        const msgs = Array.isArray(r.messages) ? r.messages : [];
        msgs.forEach(m => {
          if (!m || typeof m !== 'object') return;
          if ((m.by || 'user') !== 'user') return; // 只把用户的建议当主条目
          totalAll += 1;
          if (!m.read) totalUnread += 1;
          if (!(m.reply && String(m.reply).trim())) totalUnreplied += 1;
          flat.push({ r, m });
        });
      });
      if (amAll) amAll.textContent = totalAll;
      if (amUnread) amUnread.textContent = totalUnread;
      if (amUnreplied) amUnreplied.textContent = totalUnreplied;

      let filtered = flat;
      if (_amLastFilter === 'unread') filtered = flat.filter(x => !x.m.read);
      else if (_amLastFilter === 'unreplied') filtered = flat.filter(x => !(x.m.reply && String(x.m.reply).trim()));
      // 倒序（按msg.id或 createdAt）
      filtered.sort((a,b) => {
        const ax = Number(a.m.id) || 0;
        const bx = Number(b.m.id) || 0;
        return bx - ax;
      });

      if (filtered.length === 0) {
        let emptyTxt = '当前筛选条件下无用户反馈';
        if (_amLastFilter === 'unread') emptyTxt = '🎉 太棒了！没有未读反馈';
        else if (_amLastFilter === 'unreplied') emptyTxt = '🎉 所有用户建议已回复';
        listEl.innerHTML = '<div style="text-align:center;color:#64748B;padding:40px 8px;font-size:13px;">' + emptyTxt + '</div>';
        if (amStatus) amStatus.textContent = '共 ' + totalAll + ' 条 · 未读 ' + totalUnread + ' · 待回复 ' + totalUnreplied;
        return;
      }
      if (amStatus) amStatus.textContent = '显示 ' + filtered.length + ' 条 · 共 ' + totalAll + ' · 未读 ' + totalUnread + ' · 待回复 ' + totalUnreplied;

      listEl.innerHTML = filtered.map(x => {
        const r = x.r;
        const m = x.m;
        const mid = Number(m.id || 0);
        const createdAt = Admin.esc(m.createdAt || '');
        const byWho = '✨ ' + Admin.esc(m.cosName || r.cosName || '用户') + ' 的建议';
        const text = Admin.esc(m.text || '');
        const hasReply = !!(m.reply && String(m.reply).trim());
        const replyText = hasReply ? Admin.esc(String(m.reply)) : '';
        const replyAt = hasReply ? Admin.esc(m.replyAt || '') : '';
        const unreadCls = !m.read ? 'msg-item-unread' : '';
        const prizeLabel = r.prizeLevel === 1 ? '一等奖' : r.prizeLevel === 2 ? '二等奖' : '谢谢参与';
        const photos = Array.isArray(r.photos) ? r.photos : [];
        const firstPhoto = photos.length > 0
          ? photos.reduce((a,b) => (Number(a.photoPosition)||999) < (Number(b.photoPosition)||999) ? a : b)
          : null;

        return `
          <div class="msg-item ${unreadCls}" data-msg-id="${mid}" data-record-id="${r.id}" style="margin-bottom:16px;">
            <div class="msg-head" style="flex-wrap:wrap;gap:10px;">
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <div class="msg-by" style="font-weight:700;">${byWho}</div>
                <button class="badge" style="padding:2px 10px;font-size:10px;cursor:pointer;background:rgba(14,165,233,0.16);color:#7DD3FC;border:1px solid rgba(14,165,233,0.32);"
                  onclick="closeAllMessagesModal();showDetailById(${r.id},true);focusMsgPanel();">🔗 定位到用户详情</button>
              </div>
              <div style="display:flex;align-items:center;gap:12px;">
                ${createdAt ? `<div class="msg-time">${createdAt}</div>` : ''}
                <div style="font-size:11px;color:#94A3B8;">🎁 ${Admin.esc(prizeLabel)} · ${Admin.esc(r.prizeName || '-')}</div>
              </div>
            </div>
            <div style="display:flex;gap:14px;margin-top:10px;align-items:flex-start;">
              ${firstPhoto ? `<img src="${Admin.esc(firstPhoto.photoUrl)}" style="width:72px;height:72px;border-radius:12px;object-fit:cover;flex-shrink:0;border:2px solid #bae6fd;cursor:pointer;display:block;" data-open-url="${Admin.esc(firstPhoto.photoUrl)}" alt="照片缩略图">` : `<div style="width:72px;height:72px;border-radius:12px;background:#f8fafc;border:1px dashed #bae6fd;flex-shrink:0;display:flex;align-items:center;justify-content:center;color:#0369a1;font-size:11px;font-weight:600;">无照片</div>`}
              <div style="flex:1;min-width:0;">
                <div class="msg-text">${text}</div>
                <div style="font-size:11px;color:#64748B;margin-top:6px;">COS：<span style="color:#94A3B8;">${Admin.esc(r.cosName || '-')}</span>　微信：<span style="color:#94A3B8;">${Admin.esc(r.wechatId || '-')}</span></div>
              </div>
            </div>
            ${hasReply ? `
              <div class="msg-reply">
                <div class="msg-reply-head">
                  <span class="msg-by">📷 我的回复</span>
                  ${replyAt ? `<span class="msg-time">${replyAt}</span>` : ''}
                </div>
                <p class="msg-reply-text">${replyText}</p>
              </div>
            ` : `
              <div class="msg-reply-form">
                <textarea class="msg-reply-input" placeholder="告诉用户：修图完成了 / 需要什么素材 / 预计多久出图..." rows="2"></textarea>
                <div class="msg-reply-actions">
                  <button class="btn btn-sm btn-ghost msg-reply-skip" data-msg-id="${mid}" data-record-id="${r.id}" title="标记为已读不回复">📖 已读</button>
                  <button class="btn btn-sm btn-green msg-reply-submit" data-msg-id="${mid}" data-record-id="${r.id}">📮 发送回复给用户</button>
                </div>
              </div>
            `}
          </div>
        `;
      }).join('');
    }

    // ========== 上传照片 ==========
    function resetPreviewPanelsHidden() {
      const ep = document.getElementById('existingPhotosPanel');
      if (ep) { ep.classList.remove('on'); }
      const pv = document.getElementById('uploadPreview');
      if (pv) { pv.classList.remove('show'); }
    }
    function openUploadModal(id, name) {
      currentUploadId = id;
      const tn = document.getElementById('uploadTargetName');
      if (tn) tn.textContent = Admin.esc(name || '用户');
      resetPreviewPanelsHidden();
      const pf = document.getElementById('photoFile'); if (pf) pf.value = '';
      const rm = document.getElementById('removePreviewBtn'); if (rm) rm.style.display = 'none';
      const pi = document.getElementById('uploadPreviewImg'); if (pi) pi.src = '';

      const r = allRecords.find(x => x.id === id);
      const photos = (r && Array.isArray(r.photos)) ? r.photos : [];
      refreshExistingPhotos(photos);

      const used = new Set(photos.map(p => Number(p.photoPosition) || 0).filter(x => x >= 1 && x <= 9));
      let firstEmpty = 1;
      for (let i = 1; i <= 9; i++) if (!used.has(i)) { firstEmpty = i; break; }
      const posInput = document.getElementById('photoPosition');
      if (posInput) {
        posInput.value = String(firstEmpty);
        posInput.oninput = function () { refreshPositionSlotsHighlight(); };
      }
      refreshPositionSlotsHighlight();
      document.getElementById('uploadModal').classList.add('show');
    }
    function closeUploadModal() {
      document.getElementById('uploadModal').classList.remove('show');
      currentUploadId = null;
      resetPreviewPanelsHidden();
    }
    function clearPreview() {
      const pf = document.getElementById('photoFile'); if (pf) pf.value = '';
      const pv = document.getElementById('uploadPreview');
      const img = document.getElementById('uploadPreviewImg');
      const rmBtn = document.getElementById('removePreviewBtn');
      if (img) img.src = '';
      if (pv) pv.classList.remove('show');
      if (rmBtn) rmBtn.style.display = 'none';
    }
    function spinPosition(delta) {
      const input = document.getElementById('photoPosition');
      let v = parseInt(input ? (input.value || '1') : '1', 10);
      if (isNaN(v)) v = 1;
      v = Math.min(9, Math.max(1, v + delta));
      if (input) input.value = String(v);
      refreshPositionSlotsHighlight();
    }
    // 刷新 9 格位置槽高亮 + 点击选中
    function refreshPositionSlotsHighlight() {
      const slotsEl = document.getElementById('positionSlots');
      const posInput = document.getElementById('photoPosition');
      if (!slotsEl) return;
      if (!slotsEl.dataset.inited) {
        slotsEl.innerHTML = '';
        for (let i = 1; i <= 9; i++) {
          const d = document.createElement('div');
          d.className = 'slot-box slot-' + i;
          d.dataset.pos = i;
          d.style.cssText = 'height:34px;line-height:32px;text-align:center;border-radius:8px;font-size:13px;font-weight:700;border:1px solid #bae6fd;background:#f0faff;color:#075985;cursor:pointer;transition:all 0.1s;user-select:none;';
          (function (ii) {
            d.onmouseover = function () { this.style.transform = 'translateY(-1px)'; };
            d.onmouseout = function () { this.style.transform = 'translateY(0)'; };
            d.onclick = function () {
              if (posInput) posInput.value = String(ii);
              refreshPositionSlotsHighlight();
            };
          })(i);
          slotsEl.appendChild(d);
        }
        slotsEl.dataset.inited = '1';
      }
      const r = allRecords.find(x => x.id === currentUploadId);
      const photos = (r && Array.isArray(r.photos)) ? r.photos : [];
      const usedMap = {};
      photos.forEach(function (p) {
        const n = Number(p.photoPosition) || 0;
        if (n >= 1 && n <= 9) usedMap[n] = p;
      });
      const cur = parseInt((posInput && posInput.value) || '1', 10) || 1;
      for (let i = 1; i <= 9; i++) {
        const s = slotsEl.querySelector('.slot-' + i);
        if (!s) continue;
        const used = !!usedMap[i];
        const selected = (i === cur);
        s.style.border = selected ? '2px solid #f59e0b' : (used ? '2px solid #0284c7' : '1px solid #bae6fd');
        s.style.background = selected ? 'linear-gradient(180deg,#fef3c7,#fde68a)' : (used ? 'linear-gradient(180deg,#bae6fd,#7dd3fc)' : '#f0faff');
        s.style.color = selected ? '#92400e' : (used ? '#0c4a6e' : '#075985');
        s.style.boxShadow = selected ? '0 0 0 3px rgba(245,158,11,0.18)' : 'none';
        s.textContent = used ? (i + ' ✓') : String(i);
      }
    }
    // 渲染"已上传照片"9格缩略图预览（让用户一眼看到已传了哪些图）
    function refreshExistingPhotos(photos) {
      const countEl = document.getElementById('currentPhotoCount');
      const panelEl = document.getElementById('existingPhotosPanel');
      const gridEl = document.getElementById('eppGrid');
      const list = Array.isArray(photos) ? photos : [];
      if (countEl) countEl.textContent = String(list.length);
      if (gridEl) {
        gridEl.innerHTML = '';
        if (list.length === 0) {
          if (panelEl) panelEl.classList.remove('on');
          refreshPositionSlotsHighlight();
          return;
        }
        const map = {};
        list.forEach(function (p) {
          const n = Number(p.photoPosition) || 0;
          if (n >= 1 && n <= 9) map[n] = p;
        });
        for (let i = 1; i <= 9; i++) {
          const p = map[i];
          const card = document.createElement('div');
          card.className = 'epp-card' + (p && p.publicApproved ? ' public-approved' : '');
          if (!p) {
            card.style.border = '1px dashed #cbd5e1';
            card.style.background = '#f8fafc';
            card.innerHTML = '<div class="epp-img-wrap" style="align-items:center;justify-content:center;"><div style="font-size:12px;color:#94a3b8;font-weight:700;position:absolute;inset:0;display:flex;align-items:center;justify-content:center;">#' + i + '</div></div>';
            gridEl.appendChild(card);
            continue;
          }
          const wrap = document.createElement('div');
          wrap.className = 'epp-img-wrap';
          const lab = document.createElement('div');
          lab.className = 'epp-pos-label';
          lab.textContent = i;
          wrap.appendChild(lab);
          const img = document.createElement('img');
          img.src = p.photoUrl || '';
          img.alt = '位置' + i;
          img.loading = 'lazy';
          wrap.appendChild(img);
          card.appendChild(wrap);
          const del = document.createElement('button');
          del.type = 'button';
          del.className = 'epp-del-btn';
          del.textContent = '×';
          if (p.uploadedBy === 'user') {
            del.title = '用户本人在前端上传的照片，管理员无权删除';
            del.disabled = true;
          } else if (p.publicApproved) {
            del.title = '管理员无权删除（用户已同意公开）';
            del.disabled = true;
          } else {
            del.title = '删除位置#' + i;
          }
          (function (photo, pos) {
            del.onclick = function (e) {
              e.stopPropagation();
              if (photo.publicApproved || photo.uploadedBy === 'user') return;
              if (!confirm('确认删除位置 #' + pos + ' 的照片吗？（服务器图片会一起删除）')) return;
              deleteSinglePhoto(photo.id || photo.photoId, pos);
            };
          })(p, i);
          card.appendChild(del);
          gridEl.appendChild(card);
        }
        if (panelEl) panelEl.classList.add('on');
      }
      refreshPositionSlotsHighlight();
    }
    function deleteSinglePhoto(photoId, position) {
      if (!currentUploadId) return;
      if (!confirm('确认删除位置 #' + position + ' 的照片吗？（文件会一起删除）')) return;
      fetch('/api/lottery/photo/' + currentUploadId + '/' + photoId, { method: 'DELETE' })
        .then(r => r.json())
        .then(d => {
          if (d.success) {
            Admin.showToast('位置 #' + position + ' 已删除');
            loadRecords();
            // 刷新当前弹窗
            const r = allRecords.find(x => x.id === currentUploadId);
            if (r) refreshExistingPhotos(Array.isArray(r.photos) ? r.photos : []);
          } else {
            Admin.showToast('删除失败: ' + (d.message || '未知错误'), 'err');
          }
        })
        .catch(err => Admin.showToast('删除失败: ' + err.message, 'err'));
    }
    function confirmUpload() {
      const fi = document.getElementById('photoFile');
      if (!fi.files || !fi.files[0]) { Admin.showToast('请选择图片文件', 'err'); return; }
      if (!currentUploadId) return;
      const posInput = document.getElementById('photoPosition');
      const pos = parseInt(posInput.value || '1', 10);
      if (isNaN(pos) || pos < 1 || pos > 9) { Admin.showToast('位置序号必须在 1 到 9 之间', 'err'); return; }

      const fd = new FormData();
      fd.append('photo', fi.files[0]);
      fd.append('photoPosition', String(pos));
      const btn = document.getElementById('confirmUpload');
      btn.disabled = true; btn.textContent = '上传中...';
      fetch('/api/lottery/photo/' + currentUploadId, { method: 'POST', body: fd })
        .then(r => r.json())
        .then(d => {
          if (d.success) {
            // 【关键修复】：用接口返回的最新 photos 立刻更新计数和九宫格预览（不依赖异步loadRecords，120ms延迟根本没刷新）
            const latestPhotos = Array.isArray(d.photos) ? d.photos : [];
            refreshExistingPhotos(latestPhotos);
            // 同步更新内存里的 allRecords，防止和服务端状态脱节
            const rIdx = allRecords.findIndex(x => x.id === currentUploadId);
            if (rIdx >= 0) {
              allRecords[rIdx].photos = latestPhotos;
              allRecords[rIdx].photoCount = latestPhotos.length;
              allRecords[rIdx].photoUploaded = latestPhotos.length > 0;
              allRecords[rIdx].photoUrl = latestPhotos[0] ? latestPhotos[0].photoUrl : null;
              // renderRecords 会在后台 loadRecords 时一起重绘，这里只重绘当前选中行保持一致
              renderRecords();
              if (selectedId === currentUploadId) showDetailById(selectedId, true);
            } else {
              loadRecords();
            }
            Admin.showToast('位置 #' + pos + ' 上传成功 · 当前 ' + latestPhotos.length + '/9 张');
            clearPreview();
            // 跳到下一个空位
            const used = new Set(latestPhotos.map(p => Number(p.photoPosition) || 0).filter(x => x >= 1 && x <= 9));
            let firstEmpty = 1;
            for (let i = 1; i <= 9; i++) if (!used.has(i)) { firstEmpty = i; break; }
            posInput.value = String(firstEmpty);
            if (latestPhotos.length >= 9) {
              setTimeout(() => {
                Admin.showToast('已达到最多9张上限');
                closeUploadModal();
              }, 400);
            }
          } else {
            Admin.showToast('上传失败: ' + (d.message || '未知错误'), 'err');
          }
        })
        .catch(err => Admin.showToast('上传失败: ' + err.message, 'err'))
        .finally(() => { btn.disabled = false; btn.textContent = '⬆ 确认上传这张'; });
    }

    function revokePhotoById(id) {
      const r = allRecords.find(x => x.id === id);
      if (!r) return;
      const photos = Array.isArray(r.photos) ? r.photos : [];
      const hasUserUploaded = photos.some(p => p.uploadedBy === 'user');
      if (hasUserUploaded) {
        Admin.showToast('该记录包含用户自己上传的照片，管理员无权删除', 'err');
        return;
      }
      if (!confirm('确定撤回这张照片吗？（服务器文件会被删除 + 记录会被清空）')) return;
      fetch('/api/lottery/photo/' + id, { method: 'DELETE' })
        .then(r => r.json())
        .then(d => {
          if (d.success) { loadRecords(); Admin.showToast('已撤回照片'); }
          else Admin.showToast('撤回失败: ' + (d.message || ''), 'err');
        })
        .catch(() => Admin.showToast('撤回失败', 'err'));
    }

    function resetLotteryById(id) {
      const r = allRecords.find(x => x.id === id);
      if (!r) return;
      const tip = r.cosName || '未知用户' + (r.ip ? ' (IP:' + r.ip + ')' : '');
      // ★ 检查是否有用户自己上传的照片
      const userPhotos = (Array.isArray(r.photos) ? r.photos : []).filter(p => p.uploadedBy === 'user');
      if (userPhotos.length > 0) {
        Admin.showToast('该记录下有 ' + userPhotos.length + ' 张用户自己上传的照片，管理员无权重置。请让用户本人撤回/删除后再操作', 'err');
        return;
      }
      const LF = String.fromCharCode(10);
      const confirmText = [
        '⚠ 确认要重置「' + tip + '」的抽奖机会吗？',
        '',
        '• 该抽奖记录会被从列表删除',
        '• 该 COS + 微信号 组合可重新抽奖',
        '• 该 IP 的当日抽奖次数限制会归零',
        '• 如有照片图片，也会一并删除'
      ].join(LF);
      if (!confirm(confirmText)) return;
      fetch('/api/lottery/reset/' + id, { method: 'POST' })
        .then(r => r.json())
        .then(d => {
          if (d.success) {
            // 如果当前选中的就是这条，关掉详情
            if (selectedId === id) closeDetail();
            loadRecords();
            Admin.showToast(d.message || '已重置抽奖机会');
          } else {
            Admin.showToast('重置失败: ' + (d.message || ''), 'err');
          }
        })
        .catch(() => Admin.showToast('重置失败，请检查网络', 'err'));
    }

    // ========== 文件预览（青白简洁风 + 已锁死 !important 解除后，直接 class 切换） ==========
    (function bindFilePreview() {
      const fi = document.getElementById('photoFile');
      const dz = document.getElementById('dropZone');
      const pv = document.getElementById('uploadPreview');
      const pvi = document.getElementById('uploadPreviewImg');
      const rmBtn = document.getElementById('removePreviewBtn');
      if (!fi) return;
      function handleFile(f) {
        if (!f) return;
        const reader = new FileReader();
        reader.onload = e => {
          if (pvi) pvi.src = e.target.result;
          // 关键修复：不再用 setAttribute 写死内联 style；直接加 .show class（admin.css 已去掉锁死的 !important）
          if (pv) pv.classList.add('show');
          if (rmBtn) rmBtn.style.display = 'block';
        };
        reader.readAsDataURL(f);
      }
      fi.addEventListener('change', e => handleFile(e.target.files && e.target.files[0]));
      if (dz) {
        dz.addEventListener('click', () => fi.click());
        ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('dragover'); }));
        ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('dragover'); }));
        dz.addEventListener('drop', e => {
          const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
          if (f) {
            try { fi.files = e.dataTransfer.files; } catch(_) {}
            handleFile(f);
          }
        });
      }
    })();

    // ========== 行内事件委托（按钮 + 点击行显示详情） ==========
    function bindTableEvents() {
      const tb = document.getElementById('recordTable');
      const dc = document.getElementById('detailContent');
      if (!tb && !dc) return;

      // 通用委托：任何带 data-open-url 的元素 → 新窗口打开
      function bindOpenDelegate(root) {
        if (!root) return;
        root.addEventListener('click', e => {
          const node = e.target && e.target.closest && e.target.closest('[data-open-url]');
          if (!node) return;
          e.stopPropagation();
          const u = node.getAttribute('data-open-url');
          if (u) window.open(u, '_blank');
        });
      }
      if (tb) bindOpenDelegate(tb);
      if (dc) bindOpenDelegate(dc);
      if (tb) tb.addEventListener('click', e => {
        const t = e.target;
        // 优先处理按钮：阻止事件冒泡到行
        if (t.classList.contains('btn-reset')) {
          e.stopPropagation();
          const id = parseInt(t.getAttribute('data-reset-id'));
          resetLotteryById(id);
          return;
        }
        if (t.classList.contains('btn-upl')) {
          e.stopPropagation();
          const id = parseInt(t.getAttribute('data-id'));
          const nm = t.getAttribute('data-name');
          openUploadModal(id, nm);
          return;
        }
        if (t.classList.contains('btn-view')) {
          e.stopPropagation();
          const u = t.getAttribute('data-open-url');
          if (u) window.open(u, '_blank');
          return;
        }
        if (t.classList.contains('btn-del')) {
          e.stopPropagation();
          const id = parseInt(t.getAttribute('data-revoke-id'));
          revokePhotoById(id);
          return;
        }
        if (t.tagName === 'IMG' && t.classList.contains('photo-thumb')) {
          e.stopPropagation();
          const u = t.getAttribute('data-open-url');
          if (u) window.open(u, '_blank');
          return;
        }
        // 点击了行：找最近的 tr.row → 既显示右侧详情，同时自动向下卡片展开（⬇箭头）
        //   用户说：点开这条卡片它往下延伸，告诉我它提了什么建议
        //   每人一张独立卡片，不再混放在所有人的弹窗里
        const tr = t.closest('tr.row');
        if (tr) {
          const id = Number(tr.getAttribute('data-id'));
          if (id) {
            showDetailById(id);
            if (typeof toggleExpandRowById === 'function') toggleExpandRowById(id);
          }
        }
      });
    }

    // ========== 导出CSV ==========
    function exportCSV() {
      if (!allRecords.length) { Admin.showToast('暂无数据可导出', 'err'); return; }
      const prizeLabels = { 1: '一等奖', 2: '二等奖', 0: '谢谢参与' };
      const rows = [['序号','COS名称','微信号','IP地址','奖品等级','奖品','抽奖时间','照片状态']];
      allRecords.forEach((r, i) => {
        rows.push([
          i + 1, r.cosName || '', r.wechatId || '', r.ip || '',
          prizeLabels[r.prizeLevel] || '-', r.prizeName || '', r.timeStr || '',
          r.photoUploaded ? '已上传' : '待上传'
        ]);
      });
      const BOM = String.fromCharCode(0xFEFF);
      const CSV_LF = String.fromCharCode(10);
      const csv = BOM + rows.map(row => row.map(c => '"' + (c == null ? '' : String(c).replace(/"/g, '""')) + '"').join(',')).join(CSV_LF);
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = '抽奖记录_' + new Date().toISOString().slice(0,10) + '.csv';
      a.click();
      Admin.showToast('CSV 已导出');
    }

    // ========== 一键重置所有抽奖记录 ==========
    function resetAllRecords() {
      if (!confirm('⚠ 确认要清空所有抽奖记录吗？\\n\\n此操作将：\\n· 删除所有用户抽奖记录\\n· 重置一等奖和二等奖库存为满\\n· 清除所有IP当日抽奖次数限制\\n\\n此操作不可恢复，建议先导出CSV备份！')) return;
      fetch('/api/admin/reset-all', { method: 'POST' })
        .then(res => res.json())
        .then(d => {
          if (d.success) {
            Admin.showToast(d.message || '重置成功');
            loadRecords();
          } else {
            Admin.showToast('重置失败: ' + (d.message || ''), 'err');
          }
        })
        .catch(() => Admin.showToast('重置失败，请检查网络', 'err'));
    }

    // ========== 【A3 用户要求】：定位到第一条有未读留言的用户（只看该用户独立留言，不混放） ==========
    function jumpFirstUnreadMsgUser() {
      try {
        if (!Array.isArray(allRecords) || allRecords.length === 0) {
          Admin.toast('暂无用户参与记录');
          return;
        }
        // 找到第一条有未读留言的记录（有messages数组且存在by=user且read=false的）
        var firstUnreadId = null;
        for (var i = 0; i < allRecords.length; i++) {
          var r = allRecords[i];
          var msgs = Array.isArray(r.messages) ? r.messages : [];
          var hasUnread = msgs.some(function(m){
            return m && typeof m === 'object' && (m.by || 'user') === 'user' && !m.read;
          });
          if (hasUnread) { firstUnreadId = r.id; break; }
        }
        // 没有未读？就找第一条有任何留言的用户
        if (firstUnreadId == null) {
          for (var j = 0; j < allRecords.length; j++) {
            var rr = allRecords[j];
            var ms = Array.isArray(rr.messages) ? rr.messages : [];
            if (ms.length > 0) { firstUnreadId = rr.id; break; }
          }
        }
        if (firstUnreadId == null) {
          Admin.toast('目前还没有任何用户留言');
          return;
        }
        // 选中该记录 + 打开详情面板 + 聚焦到留言板
        selectedId = firstUnreadId;
        if (typeof showDetailById === 'function') showDetailById(firstUnreadId, true);
        if (typeof focusMsgPanel === 'function') focusMsgPanel();
        // 滚动到该用户行
        try {
          var row = document.querySelector('#recordTable tr.row[data-id="' + firstUnreadId + '"]');
          if (row && typeof row.scrollIntoView === 'function') {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
          Admin.toast('已定位到用户记录 · 右侧详情面板=仅该用户的独立留言');
        } catch(e) {}
      } catch(e) { Admin.toast('定位失败：' + (e.message || '')); }
    }
    // 暴露到window给HTML内联onclick用
    window.jumpFirstUnreadMsgUser = jumpFirstUnreadMsgUser;

    // 【A3】不再打开所有人混放的总览弹窗：
    //   ?jumpFirstUnreadMsg=1 → 直接定位到第一条有未读留言的用户（独立详情页），不再混放
    (function(){
      try {
        var usp = new URLSearchParams(location.search || '');
        var needJump = (usp.get('jumpFirstUnreadMsg') === '1') || (usp.get('openMsgs') === '1');
        if (needJump) {
          history.replaceState && history.replaceState(null, document.title, location.pathname);
          var _tries = 0;
          var _tm = setInterval(function(){
            _tries++;
            if (Array.isArray(allRecords) && allRecords.length > 0 && typeof jumpFirstUnreadMsgUser === 'function') {
              clearInterval(_tm);
              jumpFirstUnreadMsgUser();
            } else if (_tries > 40) {
              clearInterval(_tm);
            }
          }, 500);
        }
      } catch(e) {}
    })();

    // ========== 启动 ==========
    Admin.bindSidebarLogout();
    bindTableEvents();
    // 【防闪退修复】：loadRecords 轮询期间，如果用户正在展开某行且回复框获得焦点，不做全量重绘
    let loadToken = 0;
    let pollTimer = null;
    function isUserTypingInExpand() {
      try {
        const focusEl = document.activeElement;
        if (!focusEl) return false;
        const tag = (focusEl.tagName || '').toLowerCase();
        if (tag === 'textarea' || tag === 'input') {
          // 如果焦点在展开区 tr.row-expand 或详情面板里，不做重绘
          const inExpand = focusEl.closest && (focusEl.closest('tr.row-expand') || focusEl.closest('.detail-panel') || focusEl.closest('.msg-panel'));
          if (inExpand) return true;
        }
        // 如果展开区里有非空 textarea 说明用户在打字
        const typing = document.querySelector('#recordTable tr.row-expand textarea');
        if (typing && typing.value && typing.value.trim().length > 0) return true;
      } catch (e) {}
      return false;
    }
    function tickTime() {
      const el = document.getElementById('topbarSubtitle');
      if (!el) return;
      const d = new Date();
      el.textContent = d.toLocaleString('zh-CN') + ' · 每 20 秒自动刷新（输入中暂停）';
    }
    tickTime();
    setInterval(tickTime, 1000);
    loadRecords();
    function safePoll() {
      if (document.hidden) return; // 后台标签页不请求，减少浪费
      if (isUserTypingInExpand()) return; // 用户正在写回复 → 跳过重绘，等下次
      loadRecords();
    }
    pollTimer = setInterval(safePoll, 20000); // 5 秒 → 20 秒，请求数砍 75%
    // 标签页切回可见时立刻拉一次
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        clearTimeout(pollTimer._deb);
        pollTimer._deb = setTimeout(loadRecords, 300);
      }
    });

    // 移动端侧边栏抽屉式切换
    (function() {
      var sidebar = document.querySelector('.sidebar');
      var overlay = document.getElementById('sidebarOverlay');
      var topbar = document.querySelector('.topbar');
      if (!sidebar || !overlay || !topbar) return;
      function toggleSidebar() {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('show');
      }
      topbar.addEventListener('click', function(e) {
        if (window.innerWidth <= 768 && (e.clientX < 50 || e.target === topbar)) {
          toggleSidebar();
        }
      });
      overlay.addEventListener('click', function() {
        sidebar.classList.remove('open');
        overlay.classList.remove('show');
      });
    })();
  </script>
</body>
</html>
'''


@app.route('/admin')
@admin_required
def admin_page():
    return render_template_string(ADMIN_PAGE)


@app.route('/admin/dashboard')
@admin_required
def dashboard():
    return render_template_string(DASHBOARD_PAGE)


DASHBOARD_PAGE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>数据看板 · 漫展抽奖控制台</title>
  <link rel="stylesheet" href="/css/admin.css?v=m3">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body>
  <!-- 左侧竖排导航（与记录页统一） -->
  <aside class="sidebar">
    <div class="sidebar-logo">🎁</div>
    <div class="sidebar-brand-text">抽奖管理</div>
    <div class="sidebar-divider"></div>
    <a class="sidebar-link" href="/admin" title="记录管理">
      <span>📋</span><span>记录</span>
    </a>
    <a class="sidebar-link active" href="/admin/dashboard" title="数据看板">
      <span>📊</span><span>看板</span>
    </a>
    <a class="sidebar-link" href="/" title="前台首页" target="_blank" rel="noopener">
      <span>🎯</span><span>前台</span>
    </a>
    <div class="sidebar-spacer"></div>
    <div class="sidebar-avatar" title="admin">A</div>
    <a class="sidebar-logout" href="#" data-logout title="退出登录">⏻</a>
  </aside>
  <div class="sidebar-overlay" id="sidebarOverlay"></div>

  <main class="app-main">
    <!-- 顶部栏 -->
    <header class="topbar glass" style="padding: 10px 18px;">
      <div class="topbar-title-wrap">
        <div class="topbar-icon">📊</div>
        <div>
          <div class="topbar-title">实时数据看板</div>
          <div class="topbar-subtitle" id="topbarTime">加载中...</div>
        </div>
      </div>
      <div class="topbar-actions">
        <button class="btn btn-ghost" onclick="loadAll()">🔄 刷新数据</button>
        <span class="badge badge-ok"><span class="live-dot"></span><span id="onlineBadge">LIVE</span></span>
      </div>
    </header>

    <!-- KPI 网格（5卡一行，新增：💬 留言总览一键弹出全部用户反馈） -->
    <div class="db-kpi-grid">
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon cyan">👥</div><span class="stat-mini-delta up">LIVE</span></div>
        <div class="stat-mini-value" id="k_total">0</div>
        <div class="stat-mini-label">总参与人数</div>
        <div class="stat-mini-bar"><div style="width:100%;background:linear-gradient(90deg,#00B4D8,#0077B6);"></div></div>
      </div>
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon gold">🏆</div><span class="stat-mini-delta up" id="k_p1_left">0/10</span></div>
        <div class="stat-mini-value" id="k_p1">0</div>
        <div class="stat-mini-label">一等奖 · 已抽</div>
        <div class="stat-mini-bar"><div id="k_p1_bar" style="width:0%;background:linear-gradient(90deg,#FBBF24,#F59E0B);"></div></div>
      </div>
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon green">📸</div><span class="stat-mini-delta up" id="k_up_pct">0%</span></div>
        <div class="stat-mini-value" id="k_up">0</div>
        <div class="stat-mini-label">已上传照片</div>
        <div class="stat-mini-bar"><div id="k_up_bar" style="width:0%;background:linear-gradient(90deg,#06D6A0,#059669);"></div></div>
      </div>
      <div class="stat-mini">
        <div class="stat-mini-head"><div class="stat-mini-icon purple">⏱</div><span class="stat-mini-delta up">实时</span></div>
        <div class="stat-mini-value" id="k_recent">0</div>
        <div class="stat-mini-label">近1小时参与</div>
        <div class="stat-mini-bar"><div id="k_recent_bar" style="width:0%;background:linear-gradient(90deg,#A78BFA,#8B5CF6);"></div></div>
      </div>
      <!-- 🆕 留言总览卡 · 【A3 用户要求】：不再打开所有人混放的总览弹窗
           → 改为跳转到记录页，自动选中「第一条有未读留言的用户」，只在该用户的详情面板里独立显示他自己的留言（不跟别人混在一起） -->
      <div class="stat-mini" style="cursor:pointer;" onclick="location.href='/admin?jumpFirstUnreadMsg=1'" title="点击定位到第一条有未读留言的用户，查看他独立的修图建议（不混放）">
        <div class="stat-mini-head">
          <div class="stat-mini-icon" style="background:linear-gradient(135deg,#FBBF24,#F59E0B);color:#fff;">💬</div>
          <span class="stat-mini-delta up" style="background:rgba(239,68,68,0.18);color:#FCA5A5;border-color:rgba(239,68,68,0.35);" id="k_msg_unread_label">查看首条未读</span>
        </div>
        <div class="stat-mini-value" id="k_msg_total">0</div>
        <div class="stat-mini-label">用户留言反馈</div>
        <div class="stat-mini-bar"><div id="k_msg_bar" style="width:0%;background:linear-gradient(90deg,#FBBF24,#EF4444);"></div></div>
      </div>
    </div>

    <!-- 主双栏：左折线图 + 右饼图 -->
    <div class="db-main-row">
      <div class="chart-card">
        <div class="chart-card-head">
          <div class="chart-card-title">📈 <span>抽奖趋势（按小时）</span> <span class="tag">LIVE</span></div>
          <span class="badge badge-ok" style="padding:3px 10px;font-size:11px;">每 20 秒刷新</span>
        </div>
        <div class="chart-container"><canvas id="trendChart"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-card-head">
          <div class="chart-card-title">🎁 <span>奖品分布</span> <span class="tag">统计</span></div>
          <span class="badge badge-warn" style="padding:3px 10px;font-size:11px;">共 <span id="prizeTotal">0</span> 条</span>
        </div>
        <div class="chart-container"><canvas id="prizeChart"></canvas></div>
      </div>
    </div>

    <!-- 次双栏：左照片墙 + 右时间线 -->
    <div class="db-sub-row">
      <div class="chart-card">
        <div class="chart-card-head">
          <div class="chart-card-title">📸 <span>照片墙</span> <span class="tag">照片</span></div>
          <span class="badge badge-ok" style="padding:3px 10px;font-size:11px;"><span id="photoCount">0</span> 张</span>
        </div>
        <div class="photo-wall" id="photoWall"></div>
      </div>
      <div class="chart-card">
        <div class="chart-card-head">
          <div class="chart-card-title">⏱ <span>最近参与</span> <span class="tag">时间线</span></div>
          <span class="badge badge-ok" style="padding:3px 10px;font-size:11px;">TOP 12</span>
        </div>
        <div class="timeline-list" id="timelineList"></div>
      </div>
    </div>

    <!-- 二维码 / 联系方式 管理 -->
    <div class="chart-card" style="margin-top:16px;">
      <div class="chart-card-head">
        <div class="chart-card-title">🔗 <span>扩列二维码 &amp; 联系方式</span> <span class="tag">设置</span></div>
        <span class="badge badge-ok" style="padding:3px 10px;font-size:11px;">上传后前台「扩列」区自动显示</span>
      </div>
      <div class="qr-admin-grid">
        <div class="qr-admin-item">
          <div class="qr-admin-preview">
            <img id="qqPreview" src="" alt="QQ二维码预览" style="display:none;">
            <div class="qr-admin-empty" id="qqEmpty">未上传QQ二维码</div>
          </div>
          <div class="qr-admin-info">
            <div class="qr-admin-name qq-blue">QQ</div>
            <input type="text" id="qqNumberInput" placeholder="QQ号（选填，会显示在二维码下方）" class="form-input" style="margin:8px 0;">
            <label class="btn btn-ghost" style="display:inline-block;">
              📷 上传QQ二维码
              <input type="file" id="qqFileInput" accept="image/*" style="display:none;">
            </label>
            <button class="btn btn-primary" id="qqSaveBtn" style="margin-left:8px;">保存QQ号</button>
          </div>
        </div>
        <div class="qr-admin-item">
          <div class="qr-admin-preview">
            <img id="wechatPreview" src="" alt="微信二维码预览" style="display:none;">
            <div class="qr-admin-empty" id="wechatEmpty">未上传微信二维码</div>
          </div>
          <div class="qr-admin-info">
            <div class="qr-admin-name wechat-green">微信</div>
            <input type="text" id="wechatIdInput" placeholder="微信号（选填，会显示在二维码下方）" class="form-input" style="margin:8px 0;">
            <label class="btn btn-ghost" style="display:inline-block;">
              📷 上传微信二维码
              <input type="file" id="wechatFileInput" accept="image/*" style="display:none;">
            </label>
            <button class="btn btn-primary" id="wechatSaveBtn" style="margin-left:8px;">保存微信号</button>
          </div>
        </div>
      </div>
    </div>
  </main>

  <script src="/js/admin.js?v=m3"></script>
  <script>
    let allRecords = [];
    let prizeChart = null;
    let trendChart = null;

    function tickTime() {
      const el = document.getElementById('topbarTime');
      if (!el) return;
      const d = new Date();
      el.textContent = d.toLocaleString('zh-CN') + ' · 每 20 秒自动刷新';
    }

    function loadAll() {
      fetch('/api/lottery/records')
        .then(r => r.json())
        .then(d => {
          if (d.success) {
            allRecords = d.records || [];
            renderKPI();
            renderCharts();
            renderPhotoWall();
            renderTimeline();
          }
        })
        .catch(() => Admin.showToast('加载失败，请刷新重试', 'err'));
    }

    function renderKPI() {
      const total = allRecords.length;
      const p1 = allRecords.filter(r => r.prizeLevel === 1).length;
      const up = allRecords.filter(r => r.photoUploaded).length;
      // 近1小时
      const now = Date.now();
      const recent = allRecords.filter(r => {
        try { return (now - r.id) < 3600 * 1000; } catch(e) { return false; }
      }).length;

      // 🆕 留言统计（全部 + 未读）
      let msgTotal = 0;
      let msgUnread = 0;
      allRecords.forEach(r => {
        const msgs = Array.isArray(r.messages) ? r.messages : [];
        msgs.forEach(m => {
          if (!m || typeof m !== 'object') return;
          msgTotal += 1;
          if ((m.by || 'user') === 'user' && !m.read) msgUnread += 1;
        });
      });

      document.getElementById('k_total').textContent = Admin.fmtNum(total);
      document.getElementById('k_p1').textContent = Admin.fmtNum(p1);
      document.getElementById('k_p1_left').textContent = p1 + '/10';
      document.getElementById('k_p1_bar').style.width = Math.min(100, p1 * 10) + '%';
      document.getElementById('k_up').textContent = Admin.fmtNum(up);
      const upPct = total === 0 ? 0 : Math.round(up / total * 100);
      document.getElementById('k_up_pct').textContent = upPct + '%';
      document.getElementById('k_up_bar').style.width = upPct + '%';
      document.getElementById('k_recent').textContent = Admin.fmtNum(recent);
      const recentW = total === 0 ? 0 : Math.min(100, Math.round(recent / Math.max(1, total) * 100));
      document.getElementById('k_recent_bar').style.width = recentW + '%';

      // 🆕 💬 留言KPI渲染
      const $msgTotal = document.getElementById('k_msg_total');
      const $msgUnreadLabel = document.getElementById('k_msg_unread_label');
      const $msgBar = document.getElementById('k_msg_bar');
      if ($msgTotal) $msgTotal.textContent = Admin.fmtNum(msgTotal);
      if ($msgUnreadLabel) {
        if (msgUnread > 0) {
          $msgUnreadLabel.textContent = '未读 ' + msgUnread;
          $msgUnreadLabel.style.background = 'rgba(239,68,68,0.18)';
          $msgUnreadLabel.style.color = '#FCA5A5';
          $msgUnreadLabel.style.borderColor = 'rgba(239,68,68,0.35)';
          $msgUnreadLabel.style.animation = 'pulse 1.6s ease-in-out infinite';
        } else {
          $msgUnreadLabel.textContent = msgTotal === 0 ? '暂无反馈' : '全部已读';
          $msgUnreadLabel.style.background = 'rgba(6,214,160,0.16)';
          $msgUnreadLabel.style.color = '#6EE7B7';
          $msgUnreadLabel.style.borderColor = 'rgba(6,214,160,0.32)';
          $msgUnreadLabel.style.animation = 'none';
        }
      }
      if ($msgBar) $msgBar.style.width = (total === 0 ? 0 : Math.min(100, Math.round(msgTotal / Math.max(1, total) * 100))) + '%';
    }

    function renderCharts() {
      const p1 = allRecords.filter(r => r.prizeLevel === 1).length;
      const p2 = allRecords.filter(r => r.prizeLevel === 2).length;
      const p3 = allRecords.filter(r => r.prizeLevel === 0).length;
      document.getElementById('prizeTotal').textContent = Admin.fmtNum(p1 + p2 + p3);

      // ===== 饼图：奖品分布 =====
      const pc = document.getElementById('prizeChart').getContext('2d');
      if (prizeChart) prizeChart.destroy();
      prizeChart = new Chart(pc, {
        type: 'doughnut',
        data: {
          labels: ['一等奖(20元红包)', '二等奖(手办)', '谢谢参与'],
          datasets: [{
            data: [p1, p2, p3],
            backgroundColor: [
              'rgba(251, 191, 36, 0.85)',
              'rgba(239, 68, 68, 0.85)',
              'rgba(100, 116, 139, 0.75)'
            ],
            borderColor: ['#FBBF24', '#EF4444', '#64748B'],
            borderWidth: 2,
            hoverOffset: 10
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'bottom',
              labels: { color: '#94A3B8', padding: 16, font: { size: 12 }, usePointStyle: true, pointStyle: 'circle' }
            },
            tooltip: {
              backgroundColor: 'rgba(255,255,255,0.98)',
              borderColor: '#bae6fd',
              borderWidth: 1,
              titleColor: '#0c4a6e',
              bodyColor: '#0369a1',
              padding: 12,
              cornerRadius: 12,
              displayColors: true
            }
          },
          cutout: '62%'
        }
      });

      // ===== 折线图：按小时趋势 =====
      const hourly = {};
      allRecords.forEach(r => {
        if (!r.timeStr) return;
        // "YYYY-MM-DD HH:MM:SS" → "MM-DD HH:00"
        const parts = r.timeStr.split(' ');
        if (parts.length < 2) return;
        const hm = parts[1].split(':');
        const key = parts[0].slice(5) + ' ' + (hm[0] || '00') + ':00';
        hourly[key] = (hourly[key] || 0) + 1;
      });
      const sortedKeys = Object.keys(hourly).sort();
      const useKeys = sortedKeys.slice(-14);
      const labels = useKeys.length ? useKeys : ['暂无数据'];
      const values = useKeys.length ? useKeys.map(k => hourly[k]) : [0];

      const tc = document.getElementById('trendChart').getContext('2d');
      if (trendChart) trendChart.destroy();
      const gradient = tc.createLinearGradient(0, 0, 0, 280);
      gradient.addColorStop(0, 'rgba(0, 180, 216, 0.35)');
      gradient.addColorStop(1, 'rgba(0, 180, 216, 0.02)');

      trendChart = new Chart(tc, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            label: '参与人数',
            data: values,
            borderColor: '#00B4D8',
            backgroundColor: gradient,
            fill: true,
            tension: 0.4,
            pointBackgroundColor: '#00B4D8',
            pointBorderColor: '#fff',
            pointBorderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 7,
            borderWidth: 2.5
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(255,255,255,0.98)',
              borderColor: '#7dd3fc',
              borderWidth: 1,
              titleColor: '#0c4a6e',
              bodyColor: '#0369a1',
              padding: 12,
              cornerRadius: 12
            }
          },
          scales: {
            x: {
              grid: { color: '#e0f2fe', drawBorder: false },
              ticks: { color: '#64748B', font: { size: 11 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }
            },
            y: {
              beginAtZero: true,
              grid: { color: '#e0f2fe', drawBorder: false },
              ticks: { color: '#64748B', font: { size: 11 }, precision: 0 }
            }
          }
        }
      });
    }

    function renderPhotoWall() {
      const wall = document.getElementById('photoWall');
      // 看板的照片墙：展开所有照片（单记录多张展开成多个卡片），并显示是否已同意公开状态
      const cards = [];
      (allRecords || []).forEach(r => {
        const photos = Array.isArray(r.photos) ? r.photos : (r.photoUploaded && r.photoUrl ? [{id:0, photoUrl: r.photoUrl, photoPosition:1, publicApproved:false}] : []);
        const sorted = [...photos].sort((a,b) => (Number(a.photoPosition)||999)-(Number(b.photoPosition)||999));
        sorted.forEach(p => {
          cards.push({
            rid: r.id,
            pid: p.id,
            photoUrl: p.photoUrl,
            cosName: r.cosName || '',
            timeStr: r.timeStr || '',
            photoPosition: p.photoPosition || 1,
            publicApproved: !!p.publicApproved,
            uploadedBy: p.uploadedBy || ''
          });
        });
      });
      const max = Math.min(cards.length, 54);
      const slice = cards.slice(0, max);
      document.getElementById('photoCount').textContent = Admin.fmtNum(cards.length);
      if (slice.length === 0) {
        wall.innerHTML = '<div class="photo-wall-empty"><div style="font-size:40px;opacity:.5;margin-bottom:8px;">🖼️</div>暂无照片，快去记录页上传吧~</div>';
        return;
      }
      wall.innerHTML = slice.map(c => {
        const isUserUpload = c.uploadedBy === 'user';
        const isDisabled = c.publicApproved || isUserUpload;
        let delTitle;
        if (isUserUpload) delTitle = '用户本人在前端上传的照片，管理员无权删除';
        else if (c.publicApproved) delTitle = '用户已同意公开，管理员无权删除';
        else delTitle = '删除这张照片（删除服务器图片文件+从记录中移除）';
        const delDisabledAttr = isDisabled ? 'disabled style="opacity:.3;cursor:not-allowed;"' : '';
        return `
        <div class="photo-wall-item" data-id="${c.rid}" title="${Admin.esc(c.cosName || '')} · ${Admin.esc(c.timeStr || '')} · 位置#${c.photoPosition}${c.publicApproved?' · ✅用户已同意公开':''}${isUserUpload?' · 👤用户上传':''}">
          <img src="${c.photoUrl}" alt="照片" loading="lazy" class="pw-open" data-open-url="${Admin.esc(c.photoUrl)}">
          <div class="pw-pos-badge">#${c.photoPosition}</div>
          ${c.publicApproved ? '<div class="pw-apv-badge">✅ 已公开</div>' : ''}
          ${isUserUpload ? '<div class="pw-apv-badge" style="background:#e0f2fe;color:#0369a1;">👤 用户上传</div>' : ''}
          <button class="photo-wall-del" title="${delTitle}" data-del-photo="${c.rid}" data-del-photo-pid="${c.pid}" ${delDisabledAttr}>
            🗑
          </button>
        </div>
      `}).join('');
    }

    // 照片墙事件委托（document 级别，任何重绘后仍有效）
    document.addEventListener('click', e => {
      const openNode = e.target && e.target.closest && e.target.closest('[data-open-url]');
      if (openNode) {
        e.stopPropagation();
        const u = openNode.getAttribute('data-open-url');
        if (u) window.open(u, '_blank');
        return;
      }
      const delBtn = e.target && e.target.closest && e.target.closest('[data-del-photo]');
      if (delBtn) {
        e.stopPropagation();
        if (delBtn.disabled) return;
        const rid = parseInt(delBtn.getAttribute('data-del-photo'), 10);
        const pidRaw = delBtn.getAttribute('data-del-photo-pid');
        const pid = pidRaw != null ? parseInt(pidRaw, 10) : null;
        if (Number.isNaN(rid)) return;
        deletePhotoById(rid, pid, delBtn);
      }
    });

    function deletePhotoById(rid, pid, btnEl) {
      // ★ 检查是否是用户上传的照片（前端双重保险）
      if (pid && pid > 0) {
        const rec = allRecords.find(x => x.id === rid);
        if (rec) {
          const photos = Array.isArray(rec.photos) ? rec.photos : [];
          const target = photos.find(p => (p.id || p.photoId) == pid);
          if (target && target.uploadedBy === 'user') {
            Admin.showToast('用户本人在前端上传的照片，管理员无权删除', 'err');
            if (btnEl) btnEl.disabled = false;
            return;
          }
        }
      }
      if (!(pid && pid > 0)) {
        if (!confirm('确定删除这条记录的所有照片吗？图片文件会被删除且无法恢复！')) return;
      } else {
        if (!confirm('确定删除位置对应的这张照片吗？图片文件会被删除且无法恢复！')) return;
      }
      if (btnEl) btnEl.disabled = true;
      const url = (pid && pid > 0)
        ? '/api/lottery/photo/' + rid + '/' + pid
        : '/api/lottery/photo/' + rid;
      fetch(url, { method: 'DELETE' })
        .then(r => r.json())
        .then(d => {
          if (d.success) {
            loadAll();
            Admin.showToast('照片已删除');
          } else {
            Admin.showToast('删除失败: ' + (d.message || ''), 'err');
            if (btnEl) btnEl.disabled = false;
          }
        })
        .catch(() => {
          Admin.showToast('删除失败，请检查网络', 'err');
          if (btnEl) btnEl.disabled = false;
        });
    }

    function renderTimeline() {
      const list = document.getElementById('timelineList');
      const recent = allRecords.slice(0, 12);
      if (recent.length === 0) {
        list.innerHTML = '<div style="text-align:center;padding:40px 10px;color:#475569;font-size:12px;">暂无参与记录</div>';
        return;
      }
      const prizeBadgeMap = {
        1: 'badge-prize1', 2: 'badge-prize2', 3: 'badge-prize3'
      };
      const prizeTextMap = { 1: '一等奖', 2: '二等奖', 0: '谢谢参与' };
      list.innerHTML = recent.map(r => {
        const lv = r.prizeLevel;
        const pClass = prizeBadgeMap[lv] || 'badge-prize4';
        const pText = prizeTextMap[lv] || '谢谢参与';
        const avClass = lv === 1 ? 'p1' : lv === 2 ? 'p2' : lv === 3 ? 'p3' : 'p4';
        const initial = (r.cosName || '?').slice(0, 1);
        return `
          <div class="timeline-item">
            <div class="timeline-avatar ${avClass}">${initial}</div>
            <div class="timeline-body">
              <div class="timeline-name">${Admin.esc(r.cosName || '未知用户')}</div>
              <div class="timeline-meta">
                <span>${Admin.esc(r.timeStr || '-')}</span>
              </div>
              <div class="timeline-prize"><span class="badge ${pClass}"><span class="badge-dot"></span>${Admin.esc(r.prizeName || pText)}</span></div>
            </div>
          </div>
        `;
      }).join('');
    }

    // ========== 二维码 / 联系方式管理 ==========
    function loadQrConfig() {
      fetch('/api/config', { cache: 'no-store' })
        .then(r => r.ok ? r.json() : null)
        .then(cfg => {
          if (!cfg) return;
          const qqPrev = document.getElementById('qqPreview');
          const qqEmpty = document.getElementById('qqEmpty');
          const qqNum = document.getElementById('qqNumberInput');
          if (cfg.qq_code && qqPrev) { qqPrev.src = cfg.qq_code; qqPrev.style.display = 'block'; }
          if (qqEmpty) qqEmpty.style.display = cfg.qq_code ? 'none' : 'block';
          if (qqNum) qqNum.value = cfg.qq_number || '';
          const wcPrev = document.getElementById('wechatPreview');
          const wcEmpty = document.getElementById('wechatEmpty');
          const wcId = document.getElementById('wechatIdInput');
          if (cfg.wechat_code && wcPrev) { wcPrev.src = cfg.wechat_code; wcPrev.style.display = 'block'; }
          if (wcEmpty) wcEmpty.style.display = cfg.wechat_code ? 'none' : 'block';
          if (wcId) wcId.value = cfg.wechat_id || '';
        })
        .catch(() => {});
    }
    function uploadQrCode(channel, fileInput) {
      const file = fileInput.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('channel', channel);
      fd.append('file', file);
      Admin.showToast('上传中...');
      fetch('/api/admin/qrcode', { method: 'POST', body: fd })
        .then(r => r.json())
        .then(d => {
          if (d.success) { Admin.showToast((channel === 'qq' ? 'QQ' : '微信') + '二维码已更新'); loadQrConfig(); }
          else Admin.showToast('上传失败：' + (d.message || ''), 'err');
        })
        .catch(() => Admin.showToast('上传失败，请检查网络', 'err'));
    }
    function saveContact(channel) {
      const inputId = channel === 'qq' ? 'qqNumberInput' : 'wechatIdInput';
      const field = channel === 'qq' ? 'qq_number' : 'wechat_id';
      const val = document.getElementById(inputId).value.trim();
      const body = {}; body[field] = val;
      fetch('/api/admin/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(r => r.json())
        .then(d => {
          if (d.success) Admin.showToast((channel === 'qq' ? 'QQ号' : '微信号') + '已保存');
          else Admin.showToast('保存失败', 'err');
        })
        .catch(() => Admin.showToast('保存失败', 'err'));
    }
    var _qqFI = document.getElementById('qqFileInput');
    if (_qqFI) _qqFI.addEventListener('change', function(){ uploadQrCode('qq', _qqFI); });
    var _wcFI = document.getElementById('wechatFileInput');
    if (_wcFI) _wcFI.addEventListener('change', function(){ uploadQrCode('wechat', _wcFI); });
    var _qqSB = document.getElementById('qqSaveBtn');
    if (_qqSB) _qqSB.addEventListener('click', function(){ saveContact('qq'); });
    var _wcSB = document.getElementById('wechatSaveBtn');
    if (_wcSB) _wcSB.addEventListener('click', function(){ saveContact('wechat'); });

    // ========== 启动 ==========
    Admin.bindSidebarLogout();
    tickTime();
    setInterval(tickTime, 1000);
    loadAll();
    loadQrConfig();
    let dashboardPoll = setInterval(function () {
      if (document.hidden) return;
      loadAll();
    }, 20000);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        clearTimeout(dashboardPoll._deb);
        dashboardPoll._deb = setTimeout(loadAll, 300);
      }
    });

    // 移动端侧边栏抽屉式切换
    (function() {
      var sidebar = document.querySelector('.sidebar');
      var overlay = document.getElementById('sidebarOverlay');
      var topbar = document.querySelector('.topbar');
      if (!sidebar || !overlay || !topbar) return;
      function toggleSidebar() {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('show');
      }
      topbar.addEventListener('click', function(e) {
        if (window.innerWidth <= 768 && (e.clientX < 50 || e.target === topbar)) {
          toggleSidebar();
        }
      });
      overlay.addEventListener('click', function() {
        sidebar.classList.remove('open');
        overlay.classList.remove('show');
      });
    })();
  </script>
</body>
</html>
'''


if __name__ == '__main__':
    init_data()
    print('=' * 50)
    print('  漫展抽奖系统启动成功！')
    print('  前台地址: http://0.0.0.0:5000/')
    print('  后台地址: http://0.0.0.0:5000/admin')
    print('  看板地址: http://0.0.0.0:5000/admin/dashboard')
    print('=' * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)

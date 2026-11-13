import sys
import os
import shutil

def get_app_root():
    """
    Returns the root directory of the application.
    In dev: The directory containing 'src' and 'resources'.
    In frozen (onefile): The temporary directory where resources are extracted (sys._MEIPASS).
    """
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    # src/paths.py -> src -> root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_executable_dir():
    """
    Returns the directory containing the executable (or the script in dev).
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return get_app_root()

def ensure_resources():
    """
    Ensures that the 'resources' directory exists next to the executable.
    If not, it copies it from the bundled location (sys._MEIPASS).
    """
    exe_dir = get_executable_dir()
    target_resources = os.path.join(exe_dir, "resources")
    
    # If already exists, do nothing (assume user data is there)
    if os.path.exists(target_resources):
        return target_resources
        
    # If not exists, copy from bundle
    bundled_resources = os.path.join(get_app_root(), "resources")
    
    if os.path.exists(bundled_resources):
        try:
            print(f"Extracting resources to {target_resources}...")
            # 使用自定义复制函数，排除config.json
            _copy_tree_exclude(bundled_resources, target_resources, exclude_patterns=['config.json'])
        except Exception as e:
            print(f"Error extracting resources: {e}")
            # Fallback to bundled if copy fails? 
            # If copy fails (e.g. no write permission), we might have to use bundled (read-only)
            return bundled_resources
            
    return target_resources

def _copy_tree_exclude(src, dst, exclude_patterns=None):
    """
    复制目录树，但排除指定的文件模式
    """
    if exclude_patterns is None:
        exclude_patterns = []
    
    os.makedirs(dst, exist_ok=True)
    
    for item in os.listdir(src):
        # 检查是否应该排除
        should_exclude = any(pattern in item for pattern in exclude_patterns)
        if should_exclude:
            print(f"  Excluding: {item}")
            continue
            
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        
        if os.path.isdir(s):
            _copy_tree_exclude(s, d, exclude_patterns)
        else:
            shutil.copy2(s, d)

def get_config_path():
    """
    Returns the path to the config.json file.
    Always returns the path relative to the executable (or project root in dev),
    ensuring we use the persistent config file, not the temporary bundled one.
    """
    base_dir = get_executable_dir()
    return os.path.join(base_dir, "resources", "config", "config.json")

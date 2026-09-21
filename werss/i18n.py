"""
国际化（i18n）基础设施模块。
提供翻译函数 t() 和语言切换能力，支持未来多语言扩展。

用法:
    from werss.i18n import t
    msg = t("app.title")  # 返回当前语言的翻译
    msg = t("app.welcome", name="张三")  # 带变量替换

语言文件位置: locales/<lang>.json（如 zh_CN.json, en_US.json）
语言配置: config.yaml → server.language（默认 zh_CN）
"""
import os
import json
from functools import lru_cache

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCALES_DIR = os.path.join(_BASE, 'locales')

# 默认语言
_DEFAULT_LANG = 'zh_CN'

# 当前语言（运行时可通过 set_language 切换）
_current_lang = None

# 翻译缓存：{lang: {key: value}}
_translations_cache = {}


def _get_configured_lang() -> str:
    """从 config.yaml 读取语言设置"""
    try:
        from werss.config import cfg
        return cfg.get("server.language", _DEFAULT_LANG) or _DEFAULT_LANG
    except Exception:
        return _DEFAULT_LANG


def get_current_language() -> str:
    """获取当前语言"""
    global _current_lang
    if _current_lang:
        return _current_lang
    _current_lang = _get_configured_lang()
    return _current_lang


def set_language(lang: str):
    """切换当前语言（运行时）"""
    global _current_lang
    _current_lang = lang


def _load_translations(lang: str) -> dict:
    """加载指定语言的翻译文件，带缓存"""
    if lang in _translations_cache:
        return _translations_cache[lang]
    path = os.path.join(_LOCALES_DIR, f'{lang}.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _translations_cache[lang] = data
        return data
    except FileNotFoundError:
        # 语言文件不存在，回退到默认语言
        if lang != _DEFAULT_LANG:
            return _load_translations(_DEFAULT_LANG)
        return {}
    except json.JSONDecodeError as e:
        print(f"[i18n] {lang}.json 解析失败: {e}")
        return {}
    except Exception as e:
        print(f"[i18n] {lang}.json 加载异常: {e}")
        return {}


def t(key: str, **kwargs) -> str:
    """翻译函数。
    - key: 点分路径，如 "app.title"
    - kwargs: 变量替换，如 t("app.welcome", name="张三") → "欢迎，张三"
    如果 key 不存在，返回 key 本身（降级处理，不抛异常）。
    """
    lang = get_current_language()
    translations = _load_translations(lang)

    # 点分路径查找
    parts = key.split('.')
    value = translations
    for p in parts:
        if isinstance(value, dict):
            value = value.get(p)
        else:
            value = None
            break

    if value is None:
        # 回退到默认语言
        if lang != _DEFAULT_LANG:
            default_translations = _load_translations(_DEFAULT_LANG)
            value = default_translations
            for p in parts:
                if isinstance(value, dict):
                    value = value.get(p)
                else:
                    value = None
                    break

    if value is None:
        return key  # 降级：返回 key 本身

    # 变量替换
    if kwargs and isinstance(value, str):
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value

    return str(value)


def get_available_languages() -> list:
    """获取所有可用语言列表"""
    languages = []
    if not os.path.isdir(_LOCALES_DIR):
        return languages
    for f in os.listdir(_LOCALES_DIR):
        if f.endswith('.json'):
            lang = f[:-5]  # 去掉 .json
            # 读取语言显示名
            translations = _load_translations(lang)
            label = translations.get('_meta', {}).get('label', lang)
            languages.append({"code": lang, "label": label})
    return languages


def reload_translations():
    """清空翻译缓存，下次读取时重新加载。供调试/热更新使用。"""
    _translations_cache.clear()

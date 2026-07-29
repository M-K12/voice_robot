import json
import logging
from pathlib import Path
from pypinyin import lazy_pinyin

logger = logging.getLogger("xiaoan.corrector")

class AddressCorrector:
    def __init__(self):
        # Precise pinyin to standard Chinese characters map for Jiashan region (hardcoded fallback)
        self.mapping = {
            "yaozhuang": "姚庄镇",
            "weitang": "魏塘街道",
            "luoxing": "罗星街道",
            "huimin": "惠民街道",
            "dayun": "大云镇",
            "xitang": "西塘镇",
            "ganyao": "干窑镇",
            "taozhuang": "陶庄镇",
            "tianning": "天凝镇",
            "jiashan": "嘉善"
        }

    def _load_custom_mappings(self) -> dict:
        """Dynamically load mappings from backend/static/custom_mappings.json to support hot-reloading."""
        config_path = Path(__file__).parent / "static" / "custom_mappings.json"
        if not config_path.exists():
            # Fallback if run from a different directory structure
            config_path = Path(__file__).parent.parent / "backend" / "static" / "custom_mappings.json"
            
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[AddressCorrector] Failed to load custom_mappings.json: {e}")
        return {}

    def correct(self, text: str) -> str:
        """
        Correct spelling/homophones for voice-transcribed address strings.
        Returns corrected standard address string if matched, otherwise returns original text.
        """
        if not text:
            return text

        text_lower = text.lower()
        
        # Load custom mappings dynamically
        custom_data = self._load_custom_mappings()
        address_mappings = custom_data.get("address_mapping", {})
        
        # 1. Exact string/substring search in custom mappings
        for key, standard_name in address_mappings.items():
            if key == text or key in text:
                logger.info(f"[AddressCorrector] Custom address string match: '{text}' -> '{standard_name}'")
                return standard_name

        # 2. Exact string search in hardcoded fallback mapping
        for py_key, standard_name in self.mapping.items():
            if standard_name in text or py_key == text_lower:
                logger.info(f"[AddressCorrector] Hardcoded address string match: '{text}' -> '{standard_name}'")
                return standard_name

        # 3. Pinyin matching
        try:
            py_list = lazy_pinyin(text)
            py_str = "".join(py_list).lower()
            
            if py_str:
                # 3.1 Pinyin matching for custom mappings
                for key, standard_name in address_mappings.items():
                    key_py_list = lazy_pinyin(key)
                    key_py_str = "".join(key_py_list).lower()
                    
                    if key_py_str and (key_py_str in py_str or py_str in key_py_str):
                        logger.info(f"[AddressCorrector] Custom address Pinyin match: '{text}' (pinyin: {py_str}) -> '{standard_name}' (key pinyin: {key_py_str})")
                        return standard_name
                
                # 3.2 Pinyin matching for hardcoded mappings
                for py_key, standard_name in self.mapping.items():
                    if py_key in py_str:
                        logger.info(f"[AddressCorrector] Hardcoded address Pinyin match: '{text}' (pinyin: {py_str}) -> '{standard_name}'")
                        return standard_name

                # Reverse matching for incomplete pinyins (hardcoded list)
                for py_key, standard_name in self.mapping.items():
                    if py_str in py_key:
                        logger.info(f"[AddressCorrector] Hardcoded address Reverse pinyin match: '{text}' -> '{standard_name}'")
                        return standard_name
        except Exception as e:
            logger.error(f"[AddressCorrector] Error during pinyin conversion: {e}")

        return text

    def correct_layer(self, text: str) -> str:
        """
        Correct screen layer names based on layer_mapping in custom_mappings.json
        and static/screen_layers.json.
        """
        if not text:
            return text
        
        custom_data = self._load_custom_mappings()
        layer_mappings = custom_data.get("layer_mapping", {})
        
        text_lower = text.lower().strip()
        
        # 1. Exact/Substring match in custom_mappings.json
        for key, standard_name in layer_mappings.items():
            if key in text_lower or text_lower in key:
                logger.info(f"[AddressCorrector] Custom layer match: '{text}' -> '{standard_name}'")
                return standard_name

        # 2. Check screen_layers.json
        screen_layers_path = Path(__file__).parent / "static" / "screen_layers.json"
        if not screen_layers_path.exists():
            screen_layers_path = Path(__file__).parent.parent / "backend" / "static" / "screen_layers.json"
        if screen_layers_path.exists():
            try:
                with open(screen_layers_path, "r", encoding="utf-8") as f:
                    screen_layers = json.load(f)
                    for key, info in screen_layers.items():
                        if key.startswith("_"):
                            continue
                        if key == text_lower:
                            return key
                        for kw in info.get("keywords", []):
                            if isinstance(kw, str) and (kw.lower() in text_lower or text_lower in kw.lower()):
                                logger.info(f"[AddressCorrector] Screen layer keyword match: '{text}' -> '{key}'")
                                return key
            except Exception as e:
                logger.error(f"[AddressCorrector] Error reading screen_layers.json: {e}")
                
        return text

    def correct_knowledge_category(self, text: str) -> str:
        """
        Correct knowledge categories based on knowledge_category_mapping in custom_mappings.json.
        """
        if not text:
            return text
            
        custom_data = self._load_custom_mappings()
        kb_mappings = custom_data.get("knowledge_category_mapping", {})
        
        text_lower = text.lower().strip()
        
        # 1. Exact/Substring match
        for key, standard_name in kb_mappings.items():
            if key in text_lower or text_lower in key:
                logger.info(f"[AddressCorrector] Knowledge category match: '{text}' -> '{standard_name}'")
                return standard_name
                
        return text

    def correct_general(self, text: str) -> str:
        """
        Correct general keywords or typos based on general_keyword_mapping in custom_mappings.json.
        Replaces matched keywords in the text.
        """
        if not text:
            return text
            
        custom_data = self._load_custom_mappings()
        gen_mappings = custom_data.get("general_keyword_mapping", {})
        
        corrected_text = text
        for key, replacement in gen_mappings.items():
            if key in corrected_text:
                corrected_text = corrected_text.replace(key, replacement)
                logger.info(f"[AddressCorrector] General keyword replaced: '{key}' -> '{replacement}' in '{text}'")
                
        return corrected_text

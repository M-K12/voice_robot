import os
import json
import re
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("xiaoan.knowledge")

class KnowledgeService:
    def __init__(self):
        # Resolve path offsets
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.json_data_dir = os.path.join(self.base_dir, "backend_jiashan", "data")
        self.kb_dir = os.path.join(self.base_dir, "data", "knowledge_base")
        os.makedirs(self.kb_dir, exist_ok=True)
        
        # Elements to local knowledge category file mapping
        self.category_map = {
            "risk_point": "hazard_risks",
            "hazard_risks": "hazard_risks",
            "emergency_resources": "emergency_resources",
            "protection_objects": "protection_objects",
            "shelters": "emergency_resources",
            "iot_sensors": "emergency_resources",
            "rescue_team": "emergency_resources",
            "supplies": "emergency_resources",
            "fire_passages": "hazard_risks",
            "underground_spaces": "hazard_risks",
        }

    def ensure_knowledge_base(self):
        """
        Scan and convert raw JSON data files into compiled Markdown databases if they do not exist.
        """
        index_path = os.path.join(self.json_data_dir, "jiashan_basic_data.json")
        if not os.path.exists(index_path):
            logger.warning(f"[KnowledgeService] Index file not found at: {index_path}")
            return
        
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except Exception as e:
            logger.error(f"[KnowledgeService] Failed to load index json: {e}")
            return

        for cat in index.get("categories", []):
            cat_id = cat["id"]
            cat_name = cat["name"]
            md_path = os.path.join(self.kb_dir, f"{cat_id}.md")
            
            # Skip if already compiled
            if os.path.exists(md_path):
                continue
                
            logger.info(f"[KnowledgeService] Compiling local knowledge markdown: {md_path}")
            
            md_content = f"# {cat_name}本地气象应急知识库\n\n"
            md_content += f"本文件是嘉善地区{cat_name}的结构化知识汇编，包含了：{cat.get('description', '')}。\n\n"
            
            for item in cat.get("items", []):
                item_name = item["name"]
                file_name = item["file"]
                fpath = os.path.join(self.json_data_dir, file_name)
                
                if not os.path.exists(fpath):
                    logger.info(f"[KnowledgeService] Item file not found: {fpath}, skipping...")
                    continue
                    
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception as e:
                    logger.error(f"[KnowledgeService] Failed to read {fpath}: {e}")
                    continue
                    
                if not isinstance(data, list):
                    continue
                    
                md_content += f"## {item_name} (共 {len(data)} 处)\n\n"
                
                for entry in data:
                    name = entry.get("name") or entry.get("address") or f"未命名的{item_name}"
                    addr = entry.get("address") or "暂无详细地址"
                    lng = entry.get("longitude") or entry.get("lng") or "未知"
                    lat = entry.get("latitude") or entry.get("lat") or "未知"
                    notes = entry.get("notes") or entry.get("remark") or "无"
                    
                    md_content += f"- **{name}**: 地址: {addr} (经度: {lng}, 纬度: {lat})"
                    if notes and notes != "无":
                        md_content += f" | 备注: {notes}"
                    md_content += "\n"
                md_content += "\n"
                
            try:
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                logger.info(f"[KnowledgeService] Successfully compiled: {md_path}")
            except Exception as e:
                logger.error(f"[KnowledgeService] Failed to write {md_path}: {e}")

    def search_knowledge(self, element: str, query: str = "") -> Dict[str, Any]:
        """
        Query the local markdown knowledge base.
        - If query is empty: Returns counts and statistical summaries.
        - If query is not empty: Matches lines and returns matching listings.
        """
        self.ensure_knowledge_base()

        # ── 底层类别容错与智能纠错 ──
        if element not in self.category_map and element not in ["hazard_risks", "emergency_resources", "protection_objects"]:
            element_lower = str(element).lower()
            matched_cat = None
            if any(k in element_lower for k in ["避难", "避灾", "场所", "防灾", "减灾", "shelter"]):
                matched_cat = "shelters"
            elif any(k in element_lower for k in ["队伍", "救援", "抢险", "team"]):
                matched_cat = "rescue_team"
            elif any(k in element_lower for k in ["物资", "储备", "装备", "suppl"]):
                matched_cat = "supplies"
            elif any(k in element_lower for k in ["隐患", "风险", "地灾", "hazard", "risk"]):
                matched_cat = "risk_point"

            if matched_cat:
                element = matched_cat
        
        cat_id = self.category_map.get(element)
        if not cat_id:
            # Fallback check
            if element in ["hazard_risks", "emergency_resources", "protection_objects"]:
                cat_id = element
            else:
                return {"status": "error", "message": f"未知的气象应急类别: {element}"}
                
        md_path = os.path.join(self.kb_dir, f"{cat_id}.md")
        if not os.path.exists(md_path):
            return {"status": "error", "message": f"知识库文件不存在: {md_path}"}
            
        # Case 1: Empty query, return statistical overview
        if not query:
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return {"status": "error", "message": f"读取失败: {e}"}
                
            sections = re.findall(r"##\s+(.+?)\s+\(共\s+(\d+)\s+处\)", content)
            sub_items = [{"name": s[0], "count": int(s[1])} for s in sections]
            total = sum(item["count"] for item in sub_items)
            
            detail_parts = "、".join([f"{s['name']}{s['count']}处" for s in sub_items])
            summary = f"已在大屏展示。目前嘉善相关分类共计 {total} 处，包含：{detail_parts}。"
            return {
                "status": "success",
                "total": total,
                "sub_items": sub_items,
                "summary": summary
            }
            
        # Case 2: Query is not empty, do line-by-line keyword matching
        matched_lines = []
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("- **") and query in line:
                        matched_lines.append(line.strip("- *\n"))
                        if len(matched_lines) >= 15:  # Limit return size to prevent large context payload
                            break
        except Exception as e:
            return {"status": "error", "message": f"匹配读取错误: {e}"}
            
        if matched_lines:
            summary = f"在本地知识库中，为您找到以下与“{query}”相关的应急资源/风险点：\n" + "\n".join([f"- {l}" for l in matched_lines])
            return {
                "status": "success",
                "query": query,
                "matched_count": len(matched_lines),
                "data": matched_lines,
                "summary": summary
            }
        else:
            return {
                "status": "success",
                "query": query,
                "matched_count": 0,
                "summary": f"已为您查询“{query}”相关的应急信息，但在本地知识库中暂未匹配到具体数据。已在前端大屏为您展现全域分布。"
            }

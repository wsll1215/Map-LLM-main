import os

from openai import OpenAI


class GetDeepseek:
    def __init__(self):
        base_url = (
            os.getenv("LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL", "")
            or ""
        ).strip()
        if base_url and "api.deepseek.com" in base_url and not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"

        self.client = OpenAI(
            api_key=(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "") or "").strip(),
            base_url=base_url or None,
        )
        self.model = (os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini") or "").strip()

    def get_chatglm_response(self, prompt, final_answers=None):
        if final_answers:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "请使用纯文本格式回答，严格避免任何 markdown 符号和空行。",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"{final_answers}，基于上述数据库查询结果，请严格按照以下要求回答：\n"
                            "1. 保持原有内容，保留所有信息不删减。\n"
                            "2. 长句根据语义合理换行。\n"
                            "3. 段落首行不额外缩进，不要空行。\n"
                            "4. 将类似 cm2、m2 统一整理为更规范的书写形式。\n"
                            "5. 仅执行排版优化，必要时加入数字编号。\n"
                            f"回答：{prompt}"
                        ),
                    },
                ],
                stream=False,
            )
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "请使用纯文本格式回答，不要使用任何 markdown 符号。",
                    },
                    {
                        "role": "user",
                        "content": f"请用纯文本格式回答关于路段的问题：{prompt}",
                    },
                ],
                stream=False,
            )
        return response.choices[0].message.content

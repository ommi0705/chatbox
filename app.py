import os
import json
import base64
import warnings
from datetime import datetime
from dotenv import load_dotenv

import chainlit as cl
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.messages import HumanMessage
from langchain_community.document_loaders import PyPDFLoader

# =========================
# 1️⃣ 基本設定
# =========================
warnings.filterwarnings("ignore")
os.environ["GRPC_VERBOSITY"] = "ERROR"

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    raise ValueError("❌ 請在 .env 檔案中設定 GOOGLE_API_KEY")

# =========================
# 2️⃣ Gemini 模型
# =========================
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=api_key,
    temperature=0.2,
)

prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一個親切且專業的 AI 助手。你可以處理文字、圖片與 PDF 檔案。"),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{input}"),
])

chain = prompt | llm

history_store = {}

def get_session_history(session_id: str):
    if session_id not in history_store:
        history_store[session_id] = InMemoryChatMessageHistory()
    return history_store[session_id]

wrapped_chain = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)

# =========================
# 3️⃣ 儲存對話紀錄
# =========================
def save_chat_log(chat_log):
    if not chat_log:
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    filename = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(log_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(chat_log, f, ensure_ascii=False, indent=2)

    print(f"✅ 對話紀錄已儲存至 {filepath}")

# =========================
# 4️⃣ Sidebar 歷史紀錄
# =========================
@cl.set_chat_profiles
async def chat_profiles():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, "logs")

    profiles = []

    if os.path.exists(log_dir):
        files = sorted(
            [f for f in os.listdir(log_dir) if f.endswith(".json")],
            reverse=True
        )

        for f in files[:20]:
            profiles.append(
                cl.ChatProfile(
                    name=f,
                    markdown_description="點擊載入此歷史對話"
                )
            )

    return profiles


# =========================
# 5️⃣ 點擊 Sidebar 載入對話
# =========================

    filename = thread.chat_profile

    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "logs", filename)

    if not os.path.exists(file_path):
        await cl.Message(content="❌ 找不到該歷史檔案").send()
        return

    with open(file_path, "r", encoding="utf-8") as f:
        logs = json.load(f)

    # 清空目前 session 記憶
    session_id = f"resume_{datetime.now().timestamp()}"
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("chat_log", logs)

    for entry in logs:
        role = "user" if entry.get("role") == "user" else "assistant"
        await cl.Message(
            content=entry.get("content"),
            author=role
        ).send()

# =========================
# 6️⃣ 新對話開始
# =========================
@cl.on_chat_start
async def start():
    chat_profile = cl.user_session.get("chat_profile")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, "logs")

    # 如果點的是歷史檔案
    if chat_profile and chat_profile.endswith(".json"):
        file_path = os.path.join(log_dir, chat_profile)

        if not os.path.exists(file_path):
            await cl.Message(content="❌ 找不到該歷史檔案").send()
            return

        with open(file_path, "r", encoding="utf-8") as f:
            logs = json.load(f)

        # 設定新的 session
        session_id = f"resume_{datetime.now().timestamp()}"
        cl.user_session.set("session_id", session_id)
        cl.user_session.set("chat_log", logs)

        await cl.Message(content=f"📜 已載入歷史紀錄：{chat_profile}\n").send()

        for entry in logs:
            role = "user" if entry.get("role") == "user" else "assistant"
            await cl.Message(
                content=entry.get("content"),
                author=role
            ).send()

        return

    # 否則就是新對話
    cl.user_session.set("chat_log", [])
    cl.user_session.set("session_id", f"web_{datetime.now().timestamp()}")

    await cl.Message(
        content="🤖 Gemini Web 助手已上線！\n\n拖放圖片 / PDF / 文字檔即可分析。\n輸入 save 可儲存對話。"
    ).send()

# =========================
# 7️⃣ 收到訊息
# =========================
@cl.on_message
async def main(message: cl.Message):
    session_id = cl.user_session.get("session_id")
    chat_log = cl.user_session.get("chat_log") or []

    config = {"configurable": {"session_id": session_id}}

    msg_content = []
    display_text = message.content

    # 文字
    if message.content:
        msg_content.append({"type": "text", "text": message.content})

    # 附件處理
    if message.elements:
        for element in message.elements:
            if "image" in element.mime:
                with open(element.path, "rb") as f:
                    base64_image = base64.b64encode(f.read()).decode("utf-8")
                msg_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{element.mime};base64,{base64_image}"}
                })
                display_text += f"\n[已上傳圖片: {element.name}]"

            elif "pdf" in element.mime:
                loader = PyPDFLoader(element.path)
                docs = loader.load()
                pdf_text = "\n".join([doc.page_content for doc in docs])
                msg_content.append({"type": "text", "text": pdf_text})
                display_text += f"\n[已解析 PDF: {element.name}]"

    if len(msg_content) == 1 and msg_content[0]["type"] == "text":
        final_input = msg_content[0]["text"]
    else:
        final_input = [HumanMessage(content=msg_content)]

    # 記錄使用者
    chat_log.append({
        "timestamp": datetime.now().isoformat(),
        "role": "user",
        "content": display_text
    })

    msg = cl.Message(content="")

    try:
        async for chunk in wrapped_chain.astream(
            {"input": final_input},
            config=config
        ):
            if chunk.content:
                await msg.stream_token(chunk.content)

        await msg.send()

        chat_log.append({
            "timestamp": datetime.now().isoformat(),
            "role": "ai",
            "content": msg.content
        })

        cl.user_session.set("chat_log", chat_log)

    except Exception as e:
        await cl.Message(content=f"❌ 發生錯誤: {str(e)}").send()

# =========================
# 8️⃣ 結束自動儲存
# =========================
@cl.on_chat_end
async def end():
    chat_log = cl.user_session.get("chat_log")
    save_chat_log(chat_log)

# =========================
# 9️⃣ 直接啟動
# =========================
if __name__ == "__main__":
    from chainlit.cli import run_chainlit
    run_chainlit(__file__)
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

llm = ChatOpenAI(
    model="deepseek-v4-pro",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)


def plan_task(task: str) -> str:
    prompt = (
        "你是一个任务规划器。用户会给你一个任务，请你把它拆成N个具体的子任务步骤。\n"
        "直接输出一个有序列表，每行一个步骤，格式：1. xxx\n2. xxx\n..."
        "不要输出任何其他内容。"
    )
    response = llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"任务：{task}")
    ])
    return response.content


if __name__ == "__main__":

    p = """
    @Resume-Python-2026-v5.md  任务：打开boss直聘，根据我的这份简历浏览匹配的职位，进行沟通：
@posted.md 这是一个长期记忆的文件

## 工作流程

- 使用mcp工具，只能用 mcp-driver 中的工具，不能用其它工具，如curl等，因为有我的登录信息
- 打开boss直聘，最上方导航栏有一个职位按钮，点击后可以看到我的意向求职按钮，分别有：推荐，Python(成都)，点击“Python(成都)”
- 我已经登录好了自己的账号，只查看 “Python(成都)” 意向分类下的职位
- 用工具 get_text 可以查看详细招聘要求，
  - 当职位符合要求时:必须使用 open_page 打开 【查看更多信息】 的链接，这样才能新开页面
    - 新开面面后需要使用 active_page 激活职位详情页
    - 点击“立即沟通”，没反应的话再点一次。点击后在当前页会出现一个对话框，发送：Boss您好！10年web后端开发经验，近2年专注全栈和AI应用：主导过医疗IoT微服务架构（服务多家三甲医院），独立开发3个AI相关开源项目覆盖RAG/Agent/MCP/语音识别，日常深度使用AI编程工OpenCode/Codex/Claude Code提升开发效率。技术栈覆盖Django/FastAPI/MySQL/Redis/MongoDB/Docker，从传统Web到IoT设备通信，再到AI应用
都有完整项目经验，期待与您详细交流！
    - 发送完毕后，使用 close_page 关闭职位详情页，再用 active_page 激活职位列表页，继续查看下一个职位信息，进行过沟通的职位需要追加记录到 posted.md 文件中,避免重复发送

## 注意事项
- **重要**：在列表面中当该页全部处理完成后，使用页面滚动 scroll 加载一下页，不要再重复打开分类列表（即“Python(成都)”），新分页加载完成后，直接点击当前列表页的下一个职位信息
- 符合条件的职位还要满足：招聘者：在线，刚刚活跃，3日内活跃，本周活跃，新资在12-25K之间
- 尽量用工具提供的方法，如果没有可用的方法才用执行 js 的方法（evaluate） 

发送 50 个沟通后任务就完成了
把最终的完成结果记录到 Y-md-Hi.md 文件中，如：2026-0625-1324.md


    """

    print("\n=== 子任务拆解 ===")
    print(plan_task(p))

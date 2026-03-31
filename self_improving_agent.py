import requests
import json
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class AgentResult:
    success: bool
    output: str
    reflection: str
    improvements: list[str] = field(default_factory=list)

class SelfImprovingAgent:
    def __init__(self, api_key: str, model: str = "MiniMax-M2.7"):
        self.api_key = api_key
        self.model = model
        self.history: list[AgentResult] = []

    def _call(self, messages: list[dict]) -> str:
        response = requests.post(
            "https://api.minimaxi.com/v1/text/chatcompletion_v2",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages}
        )
        return response.json()["choices"][0]["message"]["content"]

    def plan(self, task: str) -> list[dict]:
        prompt = f"""你是一个高级任务规划Agent。对于以下任务，请将其分解成具体的执行步骤。

任务: {task}

请以JSON数组格式返回步骤列表，每个步骤包含:
- action: 具体动作
- expected_outcome: 预期结果
- self_check: 如何验证成功

只返回JSON，不要有其他内容。"""
        steps_json = self._call([{"role": "user", "content": prompt}])
        return json.loads(steps_json)

    def execute_step(self, step: dict, context: dict) -> AgentResult:
        prompt = f"""执行以下步骤并反思结果:

步骤: {step['action']}
预期结果: {step['expected_outcome']}
上下文: {context}

请执行这个步骤，然后:
1. 描述实际输出
2. 反思哪里出了问题或可以改进
3. 提出具体的改进措施

以JSON格式返回，包含: success, output, reflection, improvements"""
        response = self._call([{"role": "user", "content": prompt}])
        return json.loads(response)

    def evolve(self, failed_steps: list[AgentResult]) -> str:
        prompt = f"""分析以下失败案例，提出一个改进的策略来避免这些失败:

失败案例: {json.dumps(failed_steps, ensure_ascii=False, indent=2)}

请分析根本原因，并给出一个改进的系统提示词或策略，让未来的执行更加可靠。
只返回改进策略，不要有其他内容。"""
        return self._call([{"role": "user", "content": prompt}])

    def run(self, task: str, max_retries: int = 2) -> dict:
        print(f"🎯 Planning task: {task}")
        steps = self.plan(task)
        print(f"📋 Generated {len(steps)} steps")

        evolved_strategy = None
        context = {}
        failed: list = []

        for attempt in range(max_retries):

            for i, step in enumerate(steps):
                print(f"\n⚡ Executing step {i+1}/{len(steps)}: {step['action'][:50]}...")

                if evolved_strategy:
                    context["evolved_strategy"] = evolved_strategy

                result = self.execute_step(step, context)
                self.history.append(result)

                if not result.success:
                    print(f"❌ Step {i+1} failed: {result.reflection}")
                    failed.append(result)
                else:
                    print(f"✅ Step {i+1} succeeded")

                context[step["action"]] = result.output

            if not failed:
                print("\n🎉 All steps completed successfully!")
                return {"success": True, "context": context}

            if attempt < max_retries - 1:
                print(f"\n🔄 Evolving strategy based on {len(failed)} failures...")
                evolved_strategy = self.evolve(failed)
                print(f"💡 New strategy: {evolved_strategy[:100]}...")

        return {"success": False, "failed": failed, "evolved_strategy": evolved_strategy}


if __name__ == "__main__":
    agent = SelfImprovingAgent(api_key="your-api-key")

    result = agent.run(
        task="构建一个简单的网页爬虫，获取豆瓣电影Top250的电影名称和评分，并保存为CSV文件"
    )

    print("\n" + "="*50)
    print("最终结果:", result)
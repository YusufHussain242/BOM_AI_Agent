import os
from dotenv import load_dotenv
from deepagents import create_deep_agent
from skills import SKILLS

load_dotenv()


# System prompt to steer the agent to be an expert researcher
system_prompt = """
You are the Apex Meridian iBOM Engineering Assistant. 
Your goal is to answer technical queries about Vehicle Bills of Materials using the provided tools.

### RESPONSE GUIDELINES:
1. DATA-DRIVEN: Base your answers ONLY on the results returned by your tools.
2. PRECISION: Always specify the Variant (e.g., SUV, SEDAN) and System name in your final answer.
3. FORMATTING: Use £ for costs and 'kg' for weights.
4. CONCISENESS: Keep answers to 1-2 professional sentences.
5. FALLBACK: If a tool returns no data, explain that no records exist for that specific configuration.

### MAPPING RULES:
The following is a mapping between variant codes and their full names:
- SEDAN: Apex Meridian Sedan
- SUV: Apex Meridian SUV
- COUPE: Apex Meridian Coupé
- HATCH: Apex Meridian Hatchback
- ESTATE: Apex Meridian Estate
"""

agent = create_deep_agent(
    model="google_genai:gemini-3.1-flash-lite",
    tools=SKILLS,
    system_prompt=system_prompt,
)

if __name__ == '__main__':
    print("Enter your query (or press Enter to exit):")
    user_input = input("> ")
    while user_input != "":
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_input}]})

        print(result["messages"][-1].content)

        user_input = input("> ")

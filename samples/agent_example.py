#!/usr/bin/env python3
"""
Example: Using LinkedInAgent with Claude tool_use.

This shows the full loop:
1. Send a user message + tool definitions to Claude
2. Claude decides which LinkedIn tool to call
3. We execute it via LinkedInAgent.dispatch_tool()
4. Send the result back to Claude for a final answer

Prerequisites:
  pip install anthropic
  export ANTHROPIC_API_KEY=sk-...
  linkedin-scraper login   # create session first
"""

import asyncio
import json

import anthropic

from linkedin_scraper.agent import LinkedInAgent


async def main():
    # 1. Set up the LinkedIn agent (headless browser)
    agent = LinkedInAgent(session="linkedin_session.json")

    # 2. Get tool definitions (Claude-compatible format)
    tools = agent.tool_definitions()

    # 3. Set up Claude client
    client = anthropic.Anthropic()

    # 4. User query – Claude will decide which tool(s) to call
    user_message = "Look up the LinkedIn profile of Bill Gates and tell me about his career."

    print(f"User: {user_message}\n")

    messages = [{"role": "user", "content": user_message}]

    async with agent:
        # 5. First API call – Claude may request tool use
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            tools=tools,
            messages=messages,
        )

        # 6. Tool-use loop
        while response.stop_reason == "tool_use":
            # Find the tool_use block
            tool_block = next(b for b in response.content if b.type == "tool_use")
            print(f"Claude wants to call: {tool_block.name}({json.dumps(tool_block.input)})")

            # Execute via our agent
            result = await agent.dispatch_tool(tool_block.name, tool_block.input)
            print(f"Tool returned {len(json.dumps(result))} chars of data\n")

            # Send result back to Claude
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": json.dumps(result),
                    }
                ],
            })

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                tools=tools,
                messages=messages,
            )

        # 7. Final text response
        final_text = next(b for b in response.content if hasattr(b, "text")).text
        print(f"Claude: {final_text}")


if __name__ == "__main__":
    asyncio.run(main())

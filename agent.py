import json
import logging
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

llm = ChatOpenAI(api_key=OPENAI_API_KEY, model=OPENAI_MODEL, temperature=0.7)


def plan_search(topic: str) -> dict:
    """Use LLM to generate a search plan for the given topic.

    Returns dict with keys: keywords, sites, description
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a research planning assistant. Given a research topic,
generate a search plan in JSON format.

Return ONLY valid JSON with these keys:
- "keywords": list of 2-4 search queries (strings)
- "sites": list of 2-5 specific websites to check (e.g. "github.com", "stackoverflow.com")
- "description": one sentence describing the research goal

Example:
{{"keywords": ["React vs Vue 2026", "frontend framework comparison"], "sites": ["github.com", "npmtrends.com"], "description": "Compare major frontend frameworks in 2026"}}"""),
        ("human", "Research topic: {topic}")
    ])

    chain = prompt | llm | StrOutputParser()
    result = chain.invoke({"topic": topic})

    # Parse JSON from response
    try:
        # Try to extract JSON from markdown code blocks
        if "```" in result:
            json_str = result.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
            result = json_str.strip()
        return json.loads(result)
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"Failed to parse LLM response as JSON: {result}")
        return {
            "keywords": [topic],
            "sites": ["github.com", "stackoverflow.com"],
            "description": topic,
        }


def summarize_page(url: str, content: str) -> Optional[dict]:
    """Summarize a page's content using LLM.

    Returns dict with keys: title, key_points, data, pros, cons
    """
    if not content or len(content.strip()) < 50:
        return None

    # Truncate to avoid token limits
    truncated = content[:3000]

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a technical research analyst. Analyze the given web page content
and extract key information.

Return ONLY valid JSON with these keys:
- "title": the page title or main heading
- "key_points": list of 3-5 key points (strings)
- "data": list of important numbers, metrics, or facts (strings), empty list if none
- "pros": list of advantages mentioned (strings), empty list if none
- "cons": list of disadvantages mentioned (strings), empty list if none

If the content is not relevant or too short, return null."""),
        ("human", "URL: {url}\n\nContent:\n{content}")
    ])

    chain = prompt | llm | StrOutputParser()
    result = chain.invoke({"url": url, "content": truncated})

    try:
        if "```" in result:
            json_str = result.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
            result = json_str.strip()
        if result.strip().lower() == "null":
            return None
        return json.loads(result)
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"Failed to parse page summary for {url}")
        return None


def generate_review(topic: str, summaries: list[dict]) -> str:
    """Generate a comprehensive review from all page summaries.

    Returns the review as HTML content (body only, no <html> wrapper).
    """
    # Build context from summaries
    context_parts = []
    for i, s in enumerate(summaries, 1):
        if s is None:
            continue
        part = f"--- Source {i}: {s.get('title', 'Unknown')} ---\n"
        part += f"Key points: {'; '.join(s.get('key_points', []))}\n"
        if s.get('data'):
            part += f"Data: {'; '.join(s['data'])}\n"
        if s.get('pros'):
            part += f"Pros: {'; '.join(s['pros'])}\n"
        if s.get('cons'):
            part += f"Cons: {'; '.join(s['cons'])}\n"
        context_parts.append(part)

    context = "\n".join(context_parts)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a technical research writer. Given research findings from multiple sources,
write a comprehensive review in HTML format.

Return ONLY the HTML body content (no <html>, <head>, or <body> tags).
Use these HTML elements:
- <h1> for the main title
- <h2> for section headers
- <p> for paragraphs
- <ul>/<li> for lists
- <table>/<tr>/<td> for comparisons
- <strong> for emphasis

Structure:
1. <h1> title with the research topic
2. <h2> Summary (2-3 paragraph overview)
3. <h2> Detailed Analysis (breakdown of findings)
4. <h2> Comparison (if comparing technologies, use a table)
5. <h2> Pros and Cons (structured lists)
6. <h2> Conclusion (recommendation based on evidence)

Write in a clear, professional tone. Cite specific data when available."""),
        ("human", "Research topic: {topic}\n\nFindings:\n{context}")
    ])

    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"topic": topic, "context": context})

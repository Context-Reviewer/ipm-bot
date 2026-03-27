import argparse
from openai import OpenAI

client = OpenAI()
MODEL = "gpt-5.4-mini"


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"[ERROR READING FILE {path}: {e}]"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--extra", nargs="*", default=[])

    args = parser.parse_args()

    file_contents = ""

    for f in args.files:
        file_contents += f"\n\n--- FILE: {f} ---\n"
        file_contents += read_file(f)

    for f in args.extra:
        file_contents += f"\n\n--- EXTRA: {f} ---\n"
        file_contents += read_file(f)

    prompt = f"""
You are a senior Python engineer working on a deterministic automation system.

STRICT RULES:
- Do NOT expand scope
- Do NOT rewrite unrelated code
- Preserve fail-closed behavior
- Preserve deterministic logic
- Prefer minimal patches
- Do NOT return commentary-only patches

TASK:
{args.task}

CONTEXT:
{file_contents}

RESPONSE FORMAT:
1. Is this a real bug or expected behavior?
2. Root cause
3. Minimal fix (if needed)
4. Code patch (only changed sections)
5. What to test next
"""

    resp = client.responses.create(
        model=MODEL,
        input=prompt,
    )

    print("\n=== RESPONSE ===\n")
    print(resp.output_text)


if __name__ == "__main__":
    main()
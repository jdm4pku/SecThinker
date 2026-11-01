"""V2: identical public task inputs and complete-code output across strategies."""
from prompt_baselines.core import ROOT, LANG
PROMPT_DIR = ROOT / "config/secthinker_prompts/v2"
METHODS = ("standard", "cot", "secthinker_style")

def build_prompt(task, method):
    if method not in METHODS:
        raise ValueError("Unknown method: " + method)
    language = LANG[task["language"]]
    common = (PROMPT_DIR / "common.txt").read_text().format(language=language)
    strategy = (PROMPT_DIR / (method + ".txt")).read_text().format(language=language)
    if "problem" in task:
        context = "[Task Definition]\nDescription and Function Definition (as supplied by the dataset):\n" + task["problem"] + "\n\nAdditional Information:\nRequired entry point: " + task["entry_point"] + "\n"
    else:
        context = "[Task Definition]\nDescription:\nImplement the behavior specified by the comments and interfaces in the supplied source.\n\nFunction Definition and Existing Code:\n```" + task["language"] + "\n" + task["prefix"] + "\n```\n\nAdditional Information:\nThe source may be incomplete. Return the complete implementation, not only the missing continuation. Preserve existing interfaces and legitimate behavior. No additional information is provided.\n"
    return common + "\n" + context + "\n" + strategy

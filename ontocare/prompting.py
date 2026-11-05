from pathlib import Path

from .data import ROOT, digest


def contract(skill, root=ROOT, customer_experience=False):
    if skill not in {"troubleshooting", "aftersales", "shipping", "disambiguation"}:
        raise ValueError("Unknown response Skill")
    directory = Path(root) / "prompts"
    system = (directory / "customer-service.md").read_text()
    policy = (directory / "skills" / (skill + ".md")).read_text()
    if customer_experience:
        system += "\n\n" + (directory / "customer-experience.md").read_text()
        policy += "\n\n" + (directory / "skills/customer-experience/SKILL.md").read_text()
    return {"id": "customer-experience-v1" if customer_experience else "customer-service-v2", "system": system, "skill": skill, "skill_text": policy, "system_sha256": digest(system), "skill_sha256": digest(policy)}


def validate_sections(value):
    if not isinstance(value, dict) or set(value) != {"zh", "en"}:
        return False
    for language in value.values():
        if not isinstance(language, dict) or set(language) != {"summary", "actions", "questions", "limits"}:
            return False
        if any(not isinstance(language[k], str) for k in ["summary", "limits"]):
            return False
        if any(not isinstance(language[k], list) or any(not isinstance(i, str) for i in language[k]) for k in ["actions", "questions"]):
            return False
    return True

def build_entry(title: str) -> dict[str, str]:
    return {"title": title, "slug": title.lower().replace(" ", "-")}

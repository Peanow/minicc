from catalog import build_entry
from catalog.text import slugify


assert slugify("  Hello, 世界! Python  ") == "hello-python"
assert slugify("API___Design---Notes") == "api-design-notes"
assert slugify("***") == ""
assert build_entry("Hello, World!") == {
    "title": "Hello, World!",
    "slug": "hello-world",
}

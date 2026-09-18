from __future__ import annotations

DEFAULT_EXCLUDES = [
    ".git/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    "target/**",
    ".venv/**",
    "venv/**",
    "__pycache__/**",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.mp3",
    "*.mp4",
    "*.wav",
    "*.mov",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.exe",
    "*.dll",
    "*.so",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
]

TEXT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml",
    ".md", ".rst", ".txt", ".ini", ".cfg", ".env", ".sh", ".bash", ".zsh", ".sql",
    ".html", ".css", ".scss", ".xml", ".java", ".go", ".rs", ".c", ".h", ".hpp",
}

LANG_BY_EXT = {
    ".py": "py", ".pyi": "py", ".js": "js", ".jsx": "jsx", ".ts": "ts", ".tsx": "tsx",
    ".md": "md", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".java": "java", ".go": "go", ".rs": "rust", ".c": "c", ".h": "c", ".hpp": "cpp",
}

ENTRY_CANDIDATES = {
    "python": ["__main__.py", "main.py", "app.py", "cli.py", "manage.py"],
    "jsts": ["src/index.ts", "src/main.ts", "server.ts", "app.ts", "src/index.js", "src/main.js"],
    "config": ["pyproject.toml", "setup.cfg", "requirements.txt", "package.json", "tsconfig.json"],
}

DEFAULT_MAX_GROUP_KB = 512
DEFAULT_MAX_GROUP_FILES = 40

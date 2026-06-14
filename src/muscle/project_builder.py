"""
Project Builder - Multi-file project structure generation.

Architecture Decision Record (ADR):
- Auto-generates project scaffolding (requirements.txt, package.json, etc.)
- Language-specific templates
- Dependency awareness
"""

from __future__ import annotations

import re
from pathlib import Path


class ProjectBuilder:
    TEMPLATES = {
        "python": {
            "requirements.txt": "{name}\n",
            "setup.py": """from setuptools import setup, find_packages

setup(
    name="{name}",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
)
""",
            "pytest.ini": """[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
""",
            ".gitignore": """__pycache__/
*.py[cod]
*$py.class
.env
.venv/
dist/
build/
*.egg-info/
""",
            "README.md": """# {name}

{description}

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

## Testing

```bash
pytest
```
""",
        },
        "javascript": {
            "package.json": """{{
  "name": "{name}",
  "version": "1.0.0",
  "main": "index.js",
  "scripts": {{
    "start": "node index.js",
    "test": "jest"
  }},
  "dependencies": {{}}
}}""",
            ".gitignore": """node_modules/
.env
dist/
""",
            "README.md": """# {name}

{description}

## Installation

```bash
npm install
```

## Usage

```bash
npm start
```
""",
        },
        "typescript": {
            "package.json": """{{
  "name": "{name}",
  "version": "1.0.0",
  "main": "dist/index.js",
  "scripts": {{
    "build": "tsc",
    "start": "node dist/index.js",
    "test": "jest"
  }},
  "dependencies": {{}},
  "devDependencies": {{
    "typescript": "^5.0.0",
    "@types/node": "^20.0.0"
  }}
}}""",
            "tsconfig.json": """{{
  "compilerOptions": {{
    "target": "ES2020",
    "module": "commonjs",
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true
  }},
  "include": ["src/**/*"],
  "exclude": ["node_modules"]
}}""",
            ".gitignore": """node_modules/
dist/
.env
""",
            "README.md": """# {name}

{description}

## Installation

```bash
npm install
```

## Build

```bash
npm run build
```

## Usage

```bash
npm start
```
""",
        },
        "go": {
            "go.mod": """module {name}

go 1.21
""",
            ".gitignore": """*.exe
*.exe~
*.dll
*.so
*.dylib
*.test
*.out
.env
""",
            "README.md": """# {name}

{description}

## Installation

```bash
go mod download
```

## Usage

```bash
go run main.go
```

## Testing

```bash
go test ./...
```
""",
        },
        "rust": {
            "Cargo.toml": """[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[dependencies]
""",
            ".gitignore": """/target/
**/*.rs.bk
*.pdb
.env
""",
            "README.md": """# {name}

{description}

## Installation

```bash
cargo build
```

## Usage

```bash
cargo run
```

## Testing

```bash
cargo test
```
""",
        },
    }

    def __init__(self, language: str, project_name: str = "project"):
        self.language = language.lower()
        self.project_name = project_name
        self.generated_files: list[str] = []

    def build(self, output_dir: str, description: str = "MUSCLE Generated Project") -> list[str]:
        """Generate project scaffolding files."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if self.language == "python":
            self._build_python(output_path, description)
        elif self.language in ["javascript", "js"]:
            self._build_javascript(output_path, description)
        elif self.language in ["typescript", "ts"]:
            self._build_typescript(output_path, description)
        elif self.language == "go":
            self._build_go(output_path, description)
        elif self.language == "rust":
            self._build_rust(output_path, description)

        return self.generated_files

    def _build_python(self, path: Path, desc: str) -> None:
        self._write_template(
            path,
            "requirements.txt",
            self.TEMPLATES["python"]["requirements.txt"],
            desc,
        )
        self._write_template(path, "setup.py", self.TEMPLATES["python"]["setup.py"], desc)
        self._write_template(path, "pytest.ini", self.TEMPLATES["python"]["pytest.ini"], desc)
        self._write_template(path, ".gitignore", self.TEMPLATES["python"][".gitignore"], desc)
        self._write_template(path, "README.md", self.TEMPLATES["python"]["README.md"], desc)

        src_dir = path / "src"
        src_dir.mkdir(exist_ok=True)
        (src_dir / "__init__.py").touch()

    def _build_javascript(self, path: Path, desc: str) -> None:
        self._write_template(
            path, "package.json", self.TEMPLATES["javascript"]["package.json"], desc
        )
        self._write_template(path, ".gitignore", self.TEMPLATES["javascript"][".gitignore"], desc)
        self._write_template(path, "README.md", self.TEMPLATES["javascript"]["README.md"], desc)

        src_dir = path / "src"
        src_dir.mkdir(exist_ok=True)

    def _build_typescript(self, path: Path, desc: str) -> None:
        self._write_template(
            path, "package.json", self.TEMPLATES["typescript"]["package.json"], desc
        )
        self._write_template(
            path, "tsconfig.json", self.TEMPLATES["typescript"]["tsconfig.json"], desc
        )
        self._write_template(path, ".gitignore", self.TEMPLATES["typescript"][".gitignore"], desc)
        self._write_template(path, "README.md", self.TEMPLATES["typescript"]["README.md"], desc)

        src_dir = path / "src"
        src_dir.mkdir(exist_ok=True)

    def _build_go(self, path: Path, desc: str) -> None:
        self._write_template(path, "go.mod", self.TEMPLATES["go"]["go.mod"], desc)
        self._write_template(path, ".gitignore", self.TEMPLATES["go"][".gitignore"], desc)
        self._write_template(path, "README.md", self.TEMPLATES["go"]["README.md"], desc)

    def _build_rust(self, path: Path, desc: str) -> None:
        self._write_template(path, "Cargo.toml", self.TEMPLATES["rust"]["Cargo.toml"], desc)
        self._write_template(path, ".gitignore", self.TEMPLATES["rust"][".gitignore"], desc)
        self._write_template(path, "README.md", self.TEMPLATES["rust"]["README.md"], desc)

        src_dir = path / "src"
        src_dir.mkdir(exist_ok=True)

    def _write_template(self, path: Path, filename: str, content: str, description: str) -> None:
        file_path = path / filename
        file_path.write_text(content.format(name=self.project_name, description=description))
        self.generated_files.append(str(file_path))

    @staticmethod
    def detect_language_from_task(task: str) -> str | None:
        """Detect language from task description."""
        task_lower = task.lower()

        patterns = {
            "python": [
                r"\bpython\b",
                r"\bflask\b",
                r"\bdjango\b",
                r"\bfastapi\b",
                r"\bpandas\b",
                r"\bnumpy\b",
            ],
            "javascript": [r"\bjavascript\b", r"\bnode(?:\.js|js)?\b", r"\bexpress\b", r"\bnpm\b"],
            "typescript": [r"\btypescript\b", r"\bts\b", r"\btsx\b", r"\breact\b", r"\bvue\b"],
            "go": [
                r"\bgolang\b",
                r"\bgo\s+service\b",
                r"\bgo\s+lang\b",
                r"\bgoroutines?\b",
                r"\bchannels?\b",
            ],
            "rust": [r"\brust\b", r"\bcargo\b", r"\brustlang\b"],
            "java": [r"\bjava\b", r"\bspring\b", r"\bmaven\b", r"\bgradle\b"],
        }

        for lang, keywords in patterns.items():
            if any(re.search(pattern, task_lower) for pattern in keywords):
                return lang

        return None

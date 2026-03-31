# SCLE Examples

This directory contains demo projects showcasing the Self-Correcting Loop Engine (SCLE) for various languages and frameworks.

## Available Examples

### Python - FastAPI Authentication (`python_fastapi/`)
A REST API demonstration with JWT authentication, user registration, login, and CRUD operations for a todo list. Uses FastAPI, SQLAlchemy, and Pydantic.

**Run the task:**
```bash
cd python_fastapi
# Load task.txt into SCLE
```

### JavaScript/TypeScript - Express.js API (`javascript_ts/`)
A TypeScript Node.js REST API with Express.js, input validation using Zod, and PostgreSQL database connection using Prisma.

**Run the task:**
```bash
cd javascript_ts
# Load task.txt into SCLE
```

### Go - CLI Budget Tool (`go_cli/`)
A Go CLI tool for managing personal budgets with CSV import/export functionality. Demonstrates Go's strong typing, file handling, and flag parsing.

**Run the task:**
```bash
cd go_cli
# Load task.txt into SCLE
```

### Rust - Actor Model (`rust_actor/`)
A Rust project demonstrating the actor model with message passing between components. Uses the Actix framework for actor-based concurrency.

**Run the task:**
```bash
cd rust_actor
# Load task.txt into SCLE
```

## Using These Examples

1. Navigate to the example directory
2. Read the `task.txt` file for the exact task specification
3. Feed the task description to SCLE
4. SCLE will generate, evaluate, and evolve the solution through multiple iterations

## Example Structure

Each example directory contains:
- `README.md` - Description of what the example demonstrates
- `task.txt` - The exact task specification for SCLE to solve

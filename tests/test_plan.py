"""Tests for plan mode generation, parsing, and execution helpers."""

from oktigent.agent.plan import (
    Plan,
    Task,
    TaskStatus,
    build_task_prompt,
    parse_plan_response,
)


def test_parse_plan_response_valid_json():
    json_str = """{
        "summary": "Implement authentication system",
        "tasks": [
            {
                "id": "task-1",
                "title": "Create auth models",
                "description": "Define User and Token schemas",
                "files_involved": ["models/user.py"],
                "dependencies": []
            },
            {
                "id": "task-2",
                "title": "Add auth endpoints",
                "description": "Create login and register routes",
                "files_involved": ["routes/auth.py"],
                "dependencies": ["task-1"]
            }
        ]
    }"""
    plan = parse_plan_response(json_str)
    assert plan is not None
    assert plan.summary == "Implement authentication system"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].id == "task-1"
    assert plan.tasks[0].files_involved == ["models/user.py"]
    assert plan.tasks[1].dependencies == ["task-1"]
    assert plan.tasks[0].status == TaskStatus.PENDING


def test_parse_plan_response_with_markdown_fences():
    fenced_str = """```json
    {
        "summary": "Fix bug in search",
        "tasks": [
            {"id": "t1", "title": "Inspect query", "description": "Check regex", "files_involved": [], "dependencies": []}
        ]
    }
    ```"""
    plan = parse_plan_response(fenced_str)
    assert plan is not None
    assert len(plan.tasks) == 1
    assert plan.tasks[0].id == "t1"


def test_parse_plan_response_invalid():
    plan = parse_plan_response("Not a JSON document")
    assert plan is None


def test_plan_pending_and_completed_counts():
    t1 = Task(id="1", title="First", description="Desc 1", status=TaskStatus.COMPLETED)
    t2 = Task(id="2", title="Second", description="Desc 2", status=TaskStatus.PENDING)
    plan = Plan(scope="test", tasks=[t1, t2], summary="Summary")

    assert plan.completed_count() == 1
    pending = plan.pending_tasks()
    assert len(pending) == 1
    assert pending[0].id == "2"


def test_build_task_prompt():
    task = Task(
        id="task-1",
        title="Add unit tests",
        description="Write tests for files.py",
        files_involved=["tests/test_files.py"],
        dependencies=["task-0"],
    )
    prompt = build_task_prompt(task, "Refactoring plan")
    assert "Refactoring plan" in prompt
    assert "Add unit tests" in prompt
    assert "tests/test_files.py" in prompt
    assert "task-0" in prompt

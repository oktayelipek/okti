"""Tests for plan mode generation, parsing, and execution helpers."""

from okti.agent.plan import (
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


# ---------------------------------------------------------------------------
# Cost / token estimation
# ---------------------------------------------------------------------------

def test_task_estimated_tokens_scales_with_files():
    from okti.agent.plan import Task
    one = Task(id="1", title="a", description="d" * 100, files_involved=["a.py"])
    three = Task(id="2", title="a", description="d" * 100,
                 files_involved=["a.py", "b.py", "c.py"])
    assert three.estimated_tokens() > one.estimated_tokens()


def test_task_estimated_tokens_scales_with_description():
    from okti.agent.plan import Task
    short = Task(id="1", title="a", description="d" * 10, files_involved=["a.py"])
    long  = Task(id="2", title="a", description="d" * 1000, files_involved=["a.py"])
    assert long.estimated_tokens() > short.estimated_tokens()


def test_plan_total_estimated_tokens_only_pending():
    from okti.agent.plan import Plan, Task, TaskStatus
    plan = Plan(scope="test", tasks=[
        Task(id="1", title="a", description="d", files_involved=["a.py"],
             status=TaskStatus.COMPLETED),
        Task(id="2", title="b", description="d", files_involved=["b.py"]),
        Task(id="3", title="c", description="d", files_involved=["c.py"]),
    ])
    only_pending = plan.total_estimated_tokens(only_pending=True)
    all_tasks    = plan.total_estimated_tokens(only_pending=False)
    assert only_pending < all_tasks
    assert only_pending == sum(t.estimated_tokens() for t in plan.pending_tasks())


def test_plan_estimated_cost_positive_for_paid_model():
    from okti.agent.plan import Plan, Task
    plan = Plan(scope="test", tasks=[
        Task(id="1", title="a", description="d" * 500, files_involved=["a.py", "b.py"]),
        Task(id="2", title="b", description="d" * 500, files_involved=["c.py"]),
    ])
    cost = plan.estimated_cost_usd("gpt-4o")
    assert cost > 0
    assert cost < 5.0  # Sanity: no crazy numbers for a small plan


def test_plan_estimated_cost_zero_for_free_model():
    from okti.agent.plan import Plan, Task
    plan = Plan(scope="test", tasks=[
        Task(id="1", title="a", description="d" * 500, files_involved=["a.py"]),
    ])
    assert plan.estimated_cost_usd("openrouter/some-model:free") == 0.0


def test_plan_cost_summary_format():
    from okti.agent.plan import Plan, Task
    plan = Plan(scope="test", tasks=[
        Task(id="1", title="a", description="d" * 100, files_involved=["a.py"]),
    ])
    summary = plan.cost_summary("gpt-4o-mini")
    assert "1 pending task" in summary
    assert "tokens" in summary
    assert "gpt-4o-mini" in summary
    assert "$" in summary

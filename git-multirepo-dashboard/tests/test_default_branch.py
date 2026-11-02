"""Default branch selection against synthetic local Git repositories."""

import asyncio
import subprocess

import aiosqlite
import git_dashboard


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-c", "commit.gpgsign=false", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def make_repo(repo, branch):
    repo.mkdir()
    git(repo, "init", "-b", branch)
    git(repo, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
        "commit", "--allow-empty", "-m", "Synthetic initial commit")


def test_feature_checkout_resolves_main(tmp_path):
    repo = tmp_path / "repo"
    make_repo(repo, "main")
    git(repo, "branch", "master")
    git(repo, "checkout", "-b", "feature")
    assert asyncio.run(git_dashboard.get_default_branch(repo)) == "main"


def test_detached_master_only_repo_resolves_master(tmp_path):
    repo = tmp_path / "repo"
    make_repo(repo, "master")
    git(repo, "checkout", "--detach")
    assert asyncio.run(git_dashboard.get_default_branch(repo)) == "master"


def test_origin_head_wins(tmp_path):
    source = tmp_path / "source"
    make_repo(source, "trunk")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(source), str(bare)], check=True, capture_output=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
    git(clone, "branch", "main")
    assert asyncio.run(git_dashboard.get_default_branch(clone)) == "trunk"


def test_current_branch_and_main_fallback(tmp_path):
    repo = tmp_path / "repo"
    make_repo(repo, "topic")
    assert asyncio.run(git_dashboard.get_default_branch(repo)) == "topic"
    git(repo, "checkout", "--detach")
    assert asyncio.run(git_dashboard.get_default_branch(repo)) == "main"


def test_branch_scan_refreshes_stale_default(tmp_path):
    repo = tmp_path / "repo"
    make_repo(repo, "main")
    git(repo, "checkout", "-b", "feature")

    async def scan():
        async with aiosqlite.connect(":memory:") as db:
            await db.executescript(git_dashboard._SCHEMA_SQL)
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at, default_branch) VALUES (?, ?, ?, ?, ?)",
                ("synthetic", "synthetic", str(repo), "2026-01-01", "feature"),
            )
            await git_dashboard.run_branch_scan(db, "synthetic", str(repo))
            async with db.execute("SELECT default_branch FROM repositories WHERE id = 'synthetic'") as cursor:
                assert await cursor.fetchone() == ("main",)
            async with db.execute("SELECT name, is_default FROM branches ORDER BY name") as cursor:
                assert await cursor.fetchall() == [("feature", 0), ("main", 1)]

    asyncio.run(scan())

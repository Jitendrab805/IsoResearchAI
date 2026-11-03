import sqlite3
import zipfile

from isoresearch.core.db import MIGRATIONS, Database
from isoresearch.core.settings import DEFAULT_PROFILE, Settings
from isoresearch.export import backup


def test_migrations_and_default_collection(app_ctx):
    db = app_ctx.db
    assert db.schema_version() == len(MIGRATIONS)
    names = [c["name"] for c in app_ctx.repo.collections()]
    assert "All papers" in names
    # re-opening is idempotent
    db2 = Database(app_ctx.paths.database)
    assert db2.schema_version() == len(MIGRATIONS)
    assert len([c for c in app_ctx.repo.collections() if c["name"] == "All papers"]) == 1


def test_parameterized_queries_resist_injection(app_ctx, pdfs):
    app_ctx.importer.import_paths([pdfs["a"]])
    evil = "x' OR 1=1; DROP TABLE documents; --"
    assert app_ctx.repo.documents(search=evil) == []
    assert app_ctx.repo.counts()["total"] == 1
    cid = app_ctx.repo.create_collection(evil)
    assert any(c["name"] == evil for c in app_ctx.repo.collections())
    app_ctx.repo.delete_collection(cid)


def test_collections_and_tags(app_ctx, pdfs):
    app_ctx.importer.import_paths([pdfs["a"], pdfs["b"]])
    ids = [d["id"] for d in app_ctx.repo.documents()]
    cid = app_ctx.repo.create_collection("Monsoon")
    app_ctx.repo.add_to_collection(ids[:1], cid)
    assert app_ctx.repo.doc_ids_in_collections([cid]) == {ids[0]}
    app_ctx.repo.set_tags(ids[0], ["amount effect", " IsoRSM ", ""])
    assert app_ctx.repo.document(ids[0])["tags"] == ["IsoRSM", "amount effect"]
    assert [d["id"] for d in app_ctx.repo.documents(tag="IsoRSM")] == [ids[0]]
    app_ctx.repo.update_document(ids[0], display_label="My label", evil_column="x")  # unknown columns ignored
    assert app_ctx.repo.document(ids[0])["display_label"] == "My label"


def test_settings_roundtrip_and_profile(app_ctx):
    s = app_ctx.settings
    assert s.strict_offline is True
    assert s.get("privacy.allow_online_features") is False
    assert s.profile["primary_location"] == DEFAULT_PROFILE["primary_location"]
    s.set("profile.primary_location", "Port Blair (edited)")
    s2 = Settings(app_ctx.paths)
    assert s2.profile["primary_location"] == "Port Blair (edited)"


def test_corrupt_settings_fall_back_to_defaults(app_ctx):
    app_ctx.paths.settings_file.write_text("{not json", encoding="utf-8")
    s = Settings(app_ctx.paths)
    assert s.strict_offline is True


def test_backup_restore_and_delete(app_ctx, pdfs, tmp_path):
    app_ctx.importer.import_paths([pdfs["a"]])
    cid = app_ctx.chat.store.create("kept chat")
    archive = backup.create_backup(app_ctx.paths, app_ctx.settings, tmp_path / "b.zip", include_pdfs=True)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
    assert "isoresearch.sqlite3" in names and any(n.startswith("library/") for n in names)
    # change data, then restore
    app_ctx.chat.store.delete(cid)
    app_ctx.db.close()
    backup.restore_backup(app_ctx.paths, app_ctx.settings, archive)
    con = sqlite3.connect(app_ctx.paths.database)
    assert con.execute("SELECT title FROM conversations").fetchall() == [("kept chat",)]
    assert con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    con.close()
    removed = backup.delete_all_data(app_ctx.paths, app_ctx.settings)
    assert removed and not app_ctx.paths.database.exists()
    assert not any(app_ctx.settings.library_dir.iterdir())


def test_restore_rejects_foreign_zip(app_ctx, tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("hello.txt", "x")
    try:
        backup.restore_backup(app_ctx.paths, app_ctx.settings, bad)
    except ValueError as e:
        assert "not an IsoResearch AI backup" in str(e)
    else:
        raise AssertionError("expected ValueError")

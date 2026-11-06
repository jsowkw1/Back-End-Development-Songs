"""HTTP routes for the Songs service backed by MongoDB."""

import json
import os
from urllib.parse import quote_plus

from bson import json_util
from flask import jsonify, request
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from . import app


SITE_ROOT = os.path.realpath(os.path.dirname(__file__))
SONGS_FILE = os.path.join(SITE_ROOT, "data", "songs.json")
with open(SONGS_FILE, encoding="utf-8") as songs_file:
    songs_seed = json.load(songs_file)


def _create_mongo_client():
    """Build a client from an explicit URI or the course environment values."""
    uri = os.environ.get("MONGODB_URI")
    options = {"serverSelectionTimeoutMS": 3000}
    if uri:
        return MongoClient(uri, **options)

    host = os.environ.get("MONGODB_SERVICE", "localhost")
    port = int(os.environ.get("MONGODB_PORT", "27017"))
    username = os.environ.get("MONGODB_USERNAME")
    password = os.environ.get("MONGODB_PASSWORD")
    if username and password:
        return MongoClient(
            host=host,
            port=port,
            username=username,
            password=password,
            authSource=os.environ.get("MONGODB_AUTH_SOURCE", "admin"),
            **options,
        )
    return MongoClient(host=host, port=port, **options)


client = _create_mongo_client()
db = client["songs"]
songs_collection = db["songs"]
_seed_checked = False


def _ensure_seeded():
    """Load the bundled sample songs once, without clearing existing records."""
    global _seed_checked
    if not _seed_checked:
        if songs_collection.count_documents({}) == 0 and songs_seed:
            songs_collection.insert_many(songs_seed)
        _seed_checked = True


def _to_json(value):
    """Convert MongoDB ObjectIds and documents into JSON-safe values."""
    return json.loads(json_util.dumps(value))


def _database_unavailable(error):
    app.logger.error("MongoDB request failed: %s", error)
    return jsonify(message="database unavailable"), 503


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="OK"), 200


@app.route("/count", methods=["GET"])
def count():
    try:
        _ensure_seeded()
        return jsonify(count=songs_collection.count_documents({})), 200
    except PyMongoError as error:
        return _database_unavailable(error)


@app.route("/song", methods=["GET"])
def songs():
    try:
        _ensure_seeded()
        results = list(songs_collection.find({}))
        return jsonify(songs=_to_json(results)), 200
    except PyMongoError as error:
        return _database_unavailable(error)


@app.route("/song/<int:id>", methods=["GET"])
def get_song_by_id(id):
    try:
        _ensure_seeded()
        song = songs_collection.find_one({"id": id})
    except PyMongoError as error:
        return _database_unavailable(error)

    if song is None:
        return jsonify(message=f"song with id {id} not found"), 404
    return jsonify(_to_json(song)), 200


@app.route("/song", methods=["POST"])
def create_song():
    song_in = request.get_json(silent=True)
    if not isinstance(song_in, dict) or "id" not in song_in:
        return jsonify(message="song must be a JSON object with an id"), 400

    try:
        _ensure_seeded()
        if songs_collection.find_one({"id": song_in["id"]}):
            return jsonify(Message=f"song with id {song_in['id']} already present"), 302
        result = songs_collection.insert_one(song_in)
        return jsonify({"inserted id": _to_json(result.inserted_id)}), 201
    except PyMongoError as error:
        return _database_unavailable(error)


@app.route("/song", methods=["PUT"])
@app.route("/song/<int:id>", methods=["PUT"])
def update_song(id=None):
    song_in = request.get_json(silent=True)
    if not isinstance(song_in, dict):
        return jsonify(message="song must be a JSON object"), 400

    song_id = id if id is not None else song_in.get("id")
    if not isinstance(song_id, int):
        return jsonify(message="song id is required"), 400

    updated_song = dict(song_in)
    updated_song["id"] = song_id
    updated_song.pop("_id", None)

    try:
        _ensure_seeded()
        if songs_collection.find_one({"id": song_id}) is None:
            return jsonify(message="song not found"), 404
        songs_collection.update_one({"id": song_id}, {"$set": updated_song})
        result = songs_collection.find_one({"id": song_id})
        return jsonify(_to_json(result)), 200
    except PyMongoError as error:
        return _database_unavailable(error)


@app.route("/song", methods=["DELETE"])
@app.route("/song/<int:id>", methods=["DELETE"])
def delete_song(id=None):
    if id is None:
        song_in = request.get_json(silent=True)
        id = song_in.get("id") if isinstance(song_in, dict) else None
    if not isinstance(id, int):
        return jsonify(message="song id is required"), 400

    try:
        _ensure_seeded()
        result = songs_collection.delete_one({"id": id})
    except PyMongoError as error:
        return _database_unavailable(error)

    if result.deleted_count == 0:
        return jsonify(message="song not found"), 404
    return "", 204

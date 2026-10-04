import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as path;

/// Acknowledgements remove only the exact UUIDs included in that successful batch.
/// Original recorded_at values never change during retries.
class LocationQueue {
  final Database database;
  LocationQueue(this.database);
  static Future<LocationQueue> open() async {
    final db = await openDatabase(path.join(await getDatabasesPath(), 'geopulse.db'),
      version: 1, onCreate: (db, version) async {
        await db.execute('CREATE TABLE queue (event_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, payload TEXT NOT NULL)');
      });
    return LocationQueue(db);
  }
  Future<void> add(Map<String, dynamic> point) async {
    await database.insert('queue', {'event_id':point['event_id'], 'recorded_at':point['recorded_at'], 'payload':jsonEncode(point)}, conflictAlgorithm:ConflictAlgorithm.ignore);
  }
  Future<List<Map<String, dynamic>>> pending() async {
    final rows = await database.query('queue', orderBy:'recorded_at,event_id', limit:100);
    return rows.map((r)=>jsonDecode(r['payload'] as String) as Map<String,dynamic>).toList();
  }
  Future<void> acknowledge(List<Map<String,dynamic>> points) async {
    await database.transaction((tx) async {
      for (final p in points) {
        await tx.delete('queue', where:'event_id=?', whereArgs:[p['event_id']]);
      }
    });
  }
  Future<int> count() async => Sqflite.firstIntValue(await database.rawQuery('SELECT count(*) FROM queue')) ?? 0;
  Future<void> clear() async { await database.delete('queue'); }
  Future<void> close() async { await database.close(); }
}

/// Small portable test of queue acknowledgement semantics; SQLite adapter is separate.
Set<String> pendingAfterAck(Set<String> pending, Set<String> acknowledged) => pending.difference(acknowledged);

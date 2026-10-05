import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:geopulse/queue.dart';

void main(){
  sqfliteFfiInit();
  test('Durable queue preserves UUID/timestamp and removes only acknowledged points',()async{
    final db=await databaseFactoryFfi.openDatabase(inMemoryDatabasePath);
    await db.execute('CREATE TABLE queue (event_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, payload TEXT NOT NULL)');
    final queue=LocationQueue(db);
    final point={'event_id':'a','recorded_at':'2026-10-04T10:00:00Z','lng':34.46,'lat':31.51};
    await queue.add(point);await queue.add(point);
    expect(await queue.count(),1);
    final sent=await queue.pending();expect(sent.first['recorded_at'],point['recorded_at']);
    await queue.add({...point,'event_id':'b'});
    await queue.acknowledge(sent);expect(await queue.count(),1);
    expect((await queue.pending()).first['event_id'],'b');
    await queue.acknowledge(sent);expect(await queue.count(),1);
    await queue.clear();expect(await queue.count(),0);
    await queue.close();
  });
}

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:geopulse/main.dart';
import 'package:geopulse/queue.dart';

class ReadyQueue extends LocationQueue {
  final Completer<void> ready;
  ReadyQueue(super.database,this.ready);
  @override Future<int> count() async {
    final result=await super.count();
    if(!ready.isCompleted)ready.complete();
    return result;
  }
}

void main(){
  TestWidgetsFlutterBinding.ensureInitialized();sqfliteFfiInit();
  testWidgets('Tracker starts off and exposes consent-based start control',(tester)async{
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'),(call)async=>null);
    // FFI uses a real isolate; fake widget-test time cannot advance its I/O.
    await tester.runAsync(() async {
      final db=await databaseFactoryFfi.openDatabase(inMemoryDatabasePath);
      await db.execute('CREATE TABLE queue (event_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, payload TEXT NOT NULL)');
      final initialized=Completer<void>();
      await tester.pumpWidget(MaterialApp(home:Home(openQueue:()async {
        return ReadyQueue(db,initialized);
      })));
      await initialized.future;
      // Let the initialization continuation run outside fake widget time.
      await Future<void>.delayed(Duration.zero);
    });
    await tester.pumpAndSettle();await tester.tap(find.text('Tracker'));await tester.pumpAndSettle();
    expect(find.text('Start with consent'),findsOneWidget);
    expect(find.text('Stop tracking'),findsNothing);
    expect(find.textContaining('Tracking is off'),findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'),null);
  });
}

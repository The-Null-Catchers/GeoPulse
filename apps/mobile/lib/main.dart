import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:uuid/uuid.dart';
import 'queue.dart';

void main() { WidgetsFlutterBinding.ensureInitialized(); runApp(const GeoPulseApp()); }
class GeoPulseApp extends StatelessWidget {
  const GeoPulseApp({super.key});
  @override Widget build(BuildContext context) => MaterialApp(title:'GeoPulse', theme:ThemeData(brightness:Brightness.dark, colorSchemeSeed:const Color(0xff2ad1b0), useMaterial3:true),home:const Home());
}
class Home extends StatefulWidget {
  final Future<LocationQueue> Function()? openQueue;
  const Home({super.key,this.openQueue});
  @override State<Home> createState()=>_HomeState();
}
class _HomeState extends State<Home> with WidgetsBindingObserver {
  final url=TextEditingController(text:const String.fromEnvironment('API_URL',defaultValue:'https://localhost'));
  final email=TextEditingController(),password=TextEditingController(),deviceToken=TextEditingController();
  final storage=const FlutterSecureStorage();
  LocationQueue? queue;
  String access='',workspace='',status='Tracking is off. No location is collected.';
  bool tracking=false,flushing=false,operator=false;
  int buffered=0,tab=0;
  Timer? retryTimer,refreshTimer;
  StreamSubscription<Position>? positions;
  List<Map<String,dynamic>> devices=[],alerts=[];
  @override void initState() {super.initState();WidgetsBinding.instance.addObserver(this);_initialize();}
  Future<void> _initialize() async {
    queue=await (widget.openQueue?.call() ?? LocationQueue.open());
    deviceToken.text=await storage.read(key:'device_token')??'';
    final storedUrl=await storage.read(key:'api_url');if(storedUrl!=null)url.text=storedUrl;
    buffered=await queue!.count();
    retryTimer=Timer.periodic(const Duration(seconds:10),(_){if(tracking)_flush();});
    if(mounted)setState((){});
  }
  @override void didChangeAppLifecycleState(AppLifecycleState state) {
    // Foreground-only milestone: no silent tracking outside a visible screen.
    if(state==AppLifecycleState.paused || state==AppLifecycleState.detached){_stop();}
  }
  Uri endpoint(String path)=>Uri.parse('${url.text.replaceAll(RegExp(r"/$"),"")}/api/v1$path');
  Future<void> _login() async {
    try{
      final r=await http.post(endpoint('/auth/login'),headers:{'Content-Type':'application/json'},body:jsonEncode({'email':email.text,'password':password.text})).timeout(const Duration(seconds:20));
      if(r.statusCode!=200)throw Exception('Login rejected');final body=jsonDecode(r.body);
      access=body['access_token'];workspace=body['workspaces'][0]['id'];operator=true;
      await storage.write(key:'refresh_token',value:body['refresh_token']);
      await storage.write(key:'api_url',value:url.text);
      await _refresh();refreshTimer?.cancel();refreshTimer=Timer.periodic(const Duration(seconds:5),(_)=>_refresh());
      if(mounted)setState(()=>status='Operator connected. This mode does not transmit your location.');
    }catch(e){if(mounted)setState(()=>status=e.toString());}
  }
  Future<http.Response> _get(String path) async {
    var r=await http.get(endpoint(path),headers:{'Authorization':'Bearer $access','X-Workspace-ID':workspace}).timeout(const Duration(seconds:15));
    if(r.statusCode==401){
      final token=await storage.read(key:'refresh_token');
      final renewed=await http.post(endpoint('/auth/refresh'),headers:{'Content-Type':'application/json'},body:jsonEncode({'refresh_token':token}));
      if(renewed.statusCode!=200)throw Exception('Session expired');final body=jsonDecode(renewed.body);access=body['access_token'];await storage.write(key:'refresh_token',value:body['refresh_token']);
      r=await http.get(endpoint(path),headers:{'Authorization':'Bearer $access','X-Workspace-ID':workspace});
    }
    if(r.statusCode!=200)throw Exception('API request failed (${r.statusCode})');return r;
  }
  Future<void> _refresh() async {
    if(!operator)return;
    try{final d=await _get('/devices');final a=await _get('/alerts');if(mounted)setState((){devices=List<Map<String,dynamic>>.from(jsonDecode(d.body));alerts=List<Map<String,dynamic>>.from(jsonDecode(a.body));});}catch(e){if(mounted)setState(()=>status=e.toString());}
  }
  Future<void> _start() async {
    if(queue==null||deviceToken.text.isEmpty){setState(()=>status='Enter a provisioned device token.');return;}
    if(!Uri.parse(url.text).isScheme('https')){setState(()=>status='Tracking requires an HTTPS API endpoint.');return;}
    final confirmed=await showDialog<bool>(context:context,builder:(context)=>AlertDialog(title:const Text('Start location sharing?'),content:const Text('Your GPS position, speed and heading will be sent to this workspace while this app is visible. If offline, positions remain on this device until you stop or reconnect. You can stop and delete buffered data at any time.'),actions:[TextButton(onPressed:()=>Navigator.pop(context,false),child:const Text('Cancel')),FilledButton(onPressed:()=>Navigator.pop(context,true),child:const Text('Start tracking'))]));
    if(confirmed!=true)return;
    if(!await Geolocator.isLocationServiceEnabled()){if(mounted)setState(()=>status='Enable location services first.');return;}
    var permission=await Geolocator.checkPermission();if(permission==LocationPermission.denied)permission=await Geolocator.requestPermission();
    if(permission==LocationPermission.denied||permission==LocationPermission.deniedForever){if(mounted)setState(()=>status='Location permission was not granted. Tracking stays off.');return;}
    await storage.write(key:'device_token',value:deviceToken.text);await storage.write(key:'api_url',value:url.text);
    if(mounted)setState((){tracking=true;status='TRACKING ON · foreground only';});
    positions=Geolocator.getPositionStream(locationSettings:const LocationSettings(accuracy:LocationAccuracy.high,distanceFilter:10)).listen((p) async {
      if(!tracking)return;
      await queue!.add({'event_id':const Uuid().v4(),'recorded_at':p.timestamp.toUtc().toIso8601String(),'lng':p.longitude,'lat':p.latitude,'speed':p.speed.clamp(0,150),'bearing':p.heading<0?0:p.heading%360,'accuracy':p.accuracy.clamp(0,10000),'source':'mobile'});
      await _flush();
    },onError:(Object e){if(mounted)setState(()=>status='GPS error: $e');});
  }
  Future<void> _flush() async {
    if(flushing||!tracking||queue==null)return;flushing=true;
    try{final points=await queue!.pending();if(points.isEmpty)return;
      final r=await http.post(endpoint('/locations/batch'),headers:{'Content-Type':'application/json','Authorization':'Bearer ${deviceToken.text}'},body:jsonEncode({'points':points})).timeout(const Duration(seconds:20));
      if(r.statusCode==202){await queue!.acknowledge(points);}else if(r.statusCode==401){await _stop();if(mounted)setState(()=>status='Device disabled or token revoked. Tracking stopped.');}
      else {if(mounted)setState(()=>status='Offline or rejected (${r.statusCode}). Points remain queued.');}
    }catch(_){if(mounted)setState(()=>status='Offline · preserving timestamps for retry.');}
    finally{flushing=false;if(queue!=null){buffered=await queue!.count();if(mounted)setState((){});}}
  }
  Future<void> _stop() async {tracking=false;await positions?.cancel();positions=null;if(mounted)setState(()=>status='Tracking is off. No new location is collected.');}
  @override void dispose(){WidgetsBinding.instance.removeObserver(this);retryTimer?.cancel();refreshTimer?.cancel();positions?.cancel();queue?.close();for(final c in [url,email,password,deviceToken]){c.dispose();}super.dispose();}
  @override Widget build(BuildContext context)=>Scaffold(appBar:AppBar(title:const Text('GeoPulse'),actions:[if(operator)IconButton(icon:const Icon(Icons.logout),onPressed:()async{refreshTimer?.cancel();final token=await storage.read(key:'refresh_token');await http.post(endpoint('/auth/logout'),headers:{'Content-Type':'application/json'},body:jsonEncode({'refresh_token':token}));await storage.delete(key:'refresh_token');if(mounted)setState(()=>operator=false);})]),bottomNavigationBar:NavigationBar(selectedIndex:tab,onDestinationSelected:(i)=>setState(()=>tab=i),destinations:const [NavigationDestination(icon:Icon(Icons.map_outlined),label:'Operator'),NavigationDestination(icon:Icon(Icons.my_location),label:'Tracker')]),body:tab==1?_tracking():operator?_operations():_loginForm());
  Widget _loginForm()=>ListView(padding:const EdgeInsets.all(24),children:[const Text('Your operations, in focus.',style:TextStyle(fontSize:28,fontWeight:FontWeight.w600)),const SizedBox(height:24),TextField(controller:url,decoration:const InputDecoration(labelText:'HTTPS API URL')),TextField(controller:email,decoration:const InputDecoration(labelText:'Email')),TextField(controller:password,obscureText:true,decoration:const InputDecoration(labelText:'Password')),const SizedBox(height:20),FilledButton(onPressed:_login,child:const Text('Open workspace')),Text(status)]);
  Widget _tracking()=>ListView(padding:const EdgeInsets.all(24),children:[Icon(tracking?Icons.gps_fixed:Icons.gps_off,size:64,color:tracking?Colors.tealAccent:Colors.grey),const SizedBox(height:24),Text(status,style:const TextStyle(fontSize:20)),const SizedBox(height:20),TextField(controller:url,enabled:!tracking,decoration:const InputDecoration(labelText:'HTTPS API URL')),TextField(controller:deviceToken,enabled:!tracking,obscureText:true,decoration:const InputDecoration(labelText:'Provisioned device token')),const SizedBox(height:20),FilledButton(onPressed:tracking?_stop:_start,child:Text(tracking?'Stop tracking':'Start with consent')),const SizedBox(height:16),Text('$buffered points waiting for acknowledgement'),TextButton(onPressed:tracking?null:()async{await queue?.clear();buffered=0;if(mounted)setState((){});},child:const Text('Delete buffered locations')),const Text('Background collection is not enabled in this milestone. Leaving the app stops collection. Stored events upload only after you explicitly resume tracking.')]);
  Widget _operations(){final positioned=devices.where((d)=>d['lat']!=null&&d['lng']!=null).toList();return Column(children:[Expanded(child:FlutterMap(options:const MapOptions(initialCenter:LatLng(31.51,34.46),initialZoom:12),children:[TileLayer(urlTemplate:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',userAgentPackageName:'org.geopulse.app'),MarkerLayer(markers:positioned.map((d)=>Marker(point:LatLng((d['lat'] as num).toDouble(),(d['lng'] as num).toDouble()),child:GestureDetector(onTap:()=>showModalBottomSheet(context:context,builder:(_)=>Padding(padding:const EdgeInsets.all(24),child:Text('${d['name']}\n${d['state']}\nSpeed ${d['speed']} m/s\nBattery ${d['battery_level']}%\nLast GPS ${d['recorded_at']}'))),child:Icon(Icons.navigation,color:d['state']=='moving'?Colors.tealAccent:Colors.amber)))).toList()),const RichAttributionWidget(attributions:[TextSourceAttribution('OpenStreetMap contributors')])])),SizedBox(height:220,child:ListView(children:[ListTile(title:Text('${devices.length} devices · ${alerts.where((a)=>a['state']!='resolved').length} open alerts'),subtitle:Text(status)),...devices.map((d)=>ListTile(leading:const Icon(Icons.local_shipping_outlined),title:Text(d['name']),subtitle:Text('${d['state']} · ${d['recorded_at']??'No signal'}')))]))]);}
}

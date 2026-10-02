class GameSummary {
  final String eventId, sport, home, away, eventTime, date;
  final String? oddsEventId, pick;
  final Map<String,dynamic> market, projectedScore;
  final List<dynamic> propsToWatch;
  GameSummary({required this.eventId,required this.sport,required this.home,required this.away,required this.eventTime,required this.date,
    required this.market,required this.projectedScore,required this.propsToWatch,this.oddsEventId,this.pick});
  factory GameSummary.fromJson(Map<String,dynamic> j)=>GameSummary(
    eventId:'${j['event_id']}',sport:'${j['sport']}',home:'${j['home']}',away:'${j['away']}',eventTime:'${j['event_time_pacific'] ?? j['event_time']}',date:'${j['date']}',
    market:Map<String,dynamic>.from(j['market']??{}),projectedScore:Map<String,dynamic>.from(j['projected_score']??{}),
    propsToWatch:List<dynamic>.from(j['props_to_watch']??[]),oddsEventId:j['odds_event_id']?.toString(),pick:j['pick']?.toString());
}

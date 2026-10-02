import 'package:flutter/material.dart';
import '../models/game.dart';
class GameCard extends StatelessWidget{final GameSummary game;final VoidCallback onTap;const GameCard({super.key,required this.game,required this.onTap});
 @override Widget build(BuildContext c){final m=game.market;final s=game.projectedScore;return Card(child:InkWell(onTap:onTap,child:Padding(padding:const EdgeInsets.all(12),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
 Text('${game.away} @ ${game.home}',style:Theme.of(c).textTheme.titleMedium),const SizedBox(height:4),Text(game.eventTime),
 Wrap(spacing:12,children:[Text('ML: ${game.pick??'Unavailable'}'),Text('Spread: ${m['home_spread']??'—'}'),Text('Total: ${m['total']??'—'}'),Text('Score: ${s['away']??'—'}-${s['home']??'—'}')]),
 if(game.propsToWatch.isNotEmpty) Text('Props: ${game.propsToWatch.take(3).map((p)=>'${p['player']} ${p['recommended_side']??''} ${p['line']??''}').join(' • ')}',maxLines:2,overflow:TextOverflow.ellipsis)
 ])))) ;}}

"""Generate a source-controlled PBIP report + TMSL semantic model.

Run from any working directory. Power BI Desktop (Windows) is needed to render
the report. Configure its CSV parameter with configure_powerbi.py before refresh.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / 'powerbi'
SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/'


def save(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2) + '\n')


TABLES = {
    'Playback': [('event_id','int64'),('user_id','int64'),('session_id','string'),('track_id','int64'),
                 ('played_at','string'),('play_date','dateTime'),('played_ms','int64'),('duration_ms','int64'),
                 ('completion','double'),('skipped','int64'),('source','string')],
    'Tracks': [('track_id','int64'),('title','string'),('album_id','int64'),('album','string'),
               ('artist','string'),('genre','string'),('duration_ms','int64')],
    'Users': [('user_id','int64'),('listener','string')],
    'RecommendationRequests': [('request_id','string'),('user_id','int64'),('requested_at','string'),
                               ('model_version','string'),('strategy','string'),('latency_ms','double')],
    'RecommendationItems': [('request_id','string'),('track_id','int64'),('rank','int64'),('score','double')],
    'ModelEvaluation': [('strategy','string'),('k','int64'),('users','int64'),('hit_rate','double'),
                        ('ndcg','double'),('mrr','double'),('catalog_coverage','double')],
}
MEASURES = {
    'Playback': [('Total Plays','COUNTROWS(Playback)','#,0'),
                 ('Active Listeners','DISTINCTCOUNT(Playback[user_id])','#,0'),
                 ('Listening Minutes','DIVIDE(SUM(Playback[played_ms]), 60000)','#,0.0'),
                 ('Completion Rate','AVERAGE(Playback[completion])','0.0%'),
                 ('Skip Rate','AVERAGE(Playback[skipped])','0.0%')],
    'RecommendationRequests': [('Recommendation Requests','COUNTROWS(RecommendationRequests)','#,0'),
                               ('Average Latency ms','AVERAGE(RecommendationRequests[latency_ms])','0.0')],
    'RecommendationItems': [('Exposed Tracks','DISTINCTCOUNT(RecommendationItems[track_id])','#,0'),
                            ('Average Recommendation Score','AVERAGE(RecommendationItems[score])','0.000')],
    'ModelEvaluation': [('Hit Rate at 5','AVERAGE(ModelEvaluation[hit_rate])','0.0%'),
                        ('NDCG at 5','AVERAGE(ModelEvaluation[ndcg])','0.000'),
                        ('MRR at 5','AVERAGE(ModelEvaluation[mrr])','0.000'),
                        ('Catalog Coverage at 5','AVERAGE(ModelEvaluation[catalog_coverage])','0.0%')],
}


def build_model():
    tables = []
    mtypes = {'int64':'Int64.Type','string':'type text','double':'type number','dateTime':'type datetime'}
    for name, columns in TABLES.items():
        type_steps = ', '.join('{"' + col + '", ' + mtypes[kind] + '}' for col, kind in columns)
        expression = ['let', f'    Source = Csv.Document(File.Contents(DataFolder & "/{name}.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
                      '    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
                      f'    Typed = Table.TransformColumnTypes(Headers, {{{type_steps}}}, "en-US")', 'in', '    Typed']
        table = {'name':name, 'columns':[{'name':col,'dataType':kind,'sourceColumn':col,
                  'summarizeBy':'none' if col.endswith('_id') or kind in {'string','dateTime'} else 'sum'} for col,kind in columns],
                 'partitions':[{'name':name,'mode':'import','source':{'type':'m','expression':expression}}]}
        if name in MEASURES:
            table['measures'] = [{'name':n,'expression':dax,'formatString':fmt} for n,dax,fmt in MEASURES[name]]
        tables.append(table)
    relationships = [('Playback','user_id','Users','user_id'),('Playback','track_id','Tracks','track_id'),
                     ('RecommendationRequests','user_id','Users','user_id'),
                     ('RecommendationItems','request_id','RecommendationRequests','request_id'),
                     ('RecommendationItems','track_id','Tracks','track_id')]
    model = {'name':'Cadence','compatibilityLevel':1601,'model':{'culture':'en-US','defaultPowerBIDataSourceVersion':'powerBI_V3',
             'expressions':[{'name':'DataFolder','kind':'m','expression':'"C:/cadence/exports" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'}],
             'tables':tables,'relationships':[{'name':f'{a}_{col}_{b}','fromTable':a,'fromColumn':col,
                  'toTable':b,'toColumn':key,'crossFilteringBehavior':'oneDirection'} for a,col,b,key in relationships]}}
    save(PBI / 'Cadence.SemanticModel/model.bim', model)
    save(PBI / 'Cadence.SemanticModel/definition.pbism',
         {'$schema':SCHEMA+'item/semanticModel/definitionProperties/1.0.0/schema.json','version':'1.0','settings':{}})


def field(table, property, measure=False):
    return {'Measure' if measure else 'Column':{'Expression':{'SourceRef':{'Entity':table}},'Property':property}}


def projection(table, property, measure=False):
    return {'field':field(table,property,measure),'queryRef':table+'.'+property,'nativeQueryRef':property}


def visual(page, name, kind, x,y,w,h, title, roles):
    save(PBI / f'Cadence.Report/definition/pages/{page}/visuals/{name}/visual.json', {
        '$schema':SCHEMA+'item/report/definition/visualContainer/2.6.0/schema.json','name':name,
        'position':{'x':x,'y':y,'z':0,'height':h,'width':w,'tabOrder':y*10+x},
        'visual':{'visualType':kind,'query':{'queryState':{role:{'projections':items} for role,items in roles.items()}},
                  'visualContainerObjects':{'title':[{'properties':{'show':{'expr':{'Literal':{'Value':'true'}}},
                       'text':{'expr':{'Literal':{'Value':"'"+title.replace("'","''")+"'"}}},
                       'fontSize':{'expr':{'Literal':{'Value':'14D'}}}}}]}}})


def build_report():
    save(PBI/'Cadence.pbip', {'$schema':SCHEMA+'pbip/pbipProperties/1.0.0/schema.json','version':'1.0',
          'artifacts':[{'report':{'path':'Cadence.Report'}}],'settings':{'enableAutoRecovery':True}})
    save(PBI/'Cadence.Report/definition.pbir', {'$schema':SCHEMA+'item/report/definitionProperties/2.0.0/schema.json',
          'version':'4.0','datasetReference':{'byPath':{'path':'../Cadence.SemanticModel'}}})
    save(PBI/'Cadence.Report/definition/version.json',{'$schema':SCHEMA+'item/report/definition/versionMetadata/1.0.0/schema.json','version':'2.0.0'})
    save(PBI/'Cadence.Report/definition/report.json',{'$schema':SCHEMA+'item/report/definition/report/3.1.0/schema.json','themeCollection':{}})
    save(PBI/'Cadence.Report/definition/pages/pages.json',{'$schema':SCHEMA+'item/report/definition/pagesMetadata/1.0.0/schema.json',
          'pageOrder':['Engagement','ModelBehavior'],'activePageName':'Engagement'})
    for page,title in [('Engagement','Engagement · synthetic demo'),('ModelBehavior','Model behavior · offline evaluation')]:
        save(PBI/f'Cadence.Report/definition/pages/{page}/page.json',{'$schema':SCHEMA+'item/report/definition/page/2.0.0/schema.json',
              'name':page,'displayName':title,'displayOption':'FitToPage','height':720,'width':1280})
    for i,metric in enumerate(['Total Plays','Active Listeners','Completion Rate','Skip Rate']):
        visual('Engagement',f'kpi{i}','card',25+i*310,25,290,130,metric,{'Values':[projection('Playback',metric,True)]})
    visual('Engagement','daily','lineChart',25,180,780,300,'Daily play volume (UTC)',
           {'Category':[projection('Playback','play_date')],'Y':[projection('Playback','Total Plays',True)]})
    visual('Engagement','genre','clusteredBarChart',830,180,425,300,'Plays by genre',
           {'Category':[projection('Tracks','genre')],'Y':[projection('Playback','Total Plays',True)]})
    visual('Engagement','artists','tableEx',25,505,1230,190,'Artist engagement',
           {'Values':[projection('Tracks','artist'),projection('Playback','Total Plays',True),
                      projection('Playback','Listening Minutes',True),projection('Playback','Completion Rate',True)]})
    for i,(table,metric) in enumerate([('RecommendationRequests','Recommendation Requests'),
                                      ('RecommendationRequests','Average Latency ms'),('RecommendationItems','Exposed Tracks')]):
        visual('ModelBehavior',f'modelkpi{i}','card',25+i*415,25,395,130,metric,{'Values':[projection(table,metric,True)]})
    visual('ModelBehavior','baselines','tableEx',25,180,1230,230,'Temporal holdout · K=5 · 40 synthetic listeners',
           {'Values':[projection('ModelEvaluation','strategy')]+[projection('ModelEvaluation',m,True) for m in
                      ['Hit Rate at 5','NDCG at 5','MRR at 5','Catalog Coverage at 5']]})
    visual('ModelBehavior','requests','clusteredBarChart',25,440,595,255,'Requests by ranking strategy',
           {'Category':[projection('RecommendationRequests','strategy')],'Y':[projection('RecommendationRequests','Recommendation Requests',True)]})
    visual('ModelBehavior','exposure','tableEx',645,440,610,255,'Recommendation exposure scores (not probabilities)',
           {'Values':[projection('Tracks','title'),projection('RecommendationItems','Average Recommendation Score',True)]})


if __name__ == '__main__':
    build_model()
    build_report()
    print('Generated Power BI project: powerbi/Cadence.pbip')

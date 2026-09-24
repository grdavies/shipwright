"""A GitHub HTTP200 error or incomplete pagination is not zero review threads."""
import json
from pathlib import Path

import pytest
from _sw.host import github
import check_gate_lib as gate

CTX = {"owner": "grdavies", "repo": "tierforge", "apiBase": "https://api.github.com", "tokenEnv": ""}
HEAD = "5e80f798ca89ee3237db4bb7c63f3e81a9288252"


def page(nodes, more=False, cursor=None):
    return {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": cursor}}}}}}


def node(resolved=False, outdated=False):
    return {"isResolved": resolved, "isOutdated": outdated}


def adapter(monkeypatch, responses):
    calls=[]
    monkeypatch.setattr(github.common,"mock_fixture",lambda *a:None)
    def request(**kwargs):
        query=json.loads(kwargs["body"])
        calls.append(query)
        # Reproduce GitHub's actual syntax-error envelope for the old extra brace.
        if query['query'].count('{') != query['query'].count('}'):
            body={"errors":[{"message":"Expected one of SCHEMA, SCALAR, TYPE, ENUM, INPUT, UNION, INTERFACE, actual: RCURLY at [1,198]"}]}
        else:
            body=responses[min(len(calls)-1,len(responses)-1)]
        return {"verdict":"ok","statusCode":200,"body":body if isinstance(body,str) else json.dumps(body)}
    monkeypatch.setattr(github.common,"http_request",request)
    result=github._review_threads(Path('/tmp'),CTX,['--number','351'])
    return result,calls


def test_current_pr351_threads_are_counted(monkeypatch):
    (result,code),calls=adapter(monkeypatch,[page([node(),node(),node(True),node(True)])])
    assert code==0
    assert result['data']=={'unresolved':2,'actionable':2}
    assert calls[0]['variables']['c'] is None


def test_pagination_counts_every_page(monkeypatch):
    (result,code),calls=adapter(monkeypatch,[page([node(True)],True,'next'),page([node(),node(False,True)])])
    assert code==0
    assert result['data']=={'unresolved':2,'actionable':1}
    assert calls[1]['variables']['c']=='next'


@pytest.mark.parametrize('response',[
    {'errors':[{'message':'server error'}]},
    {**page([]),'errors':[{'message':'partial result'}]},
    {},[],{'data':{'repository':None}},page([{}]),page([{'isResolved':'false','isOutdated':False}]),
    '{bad json',page([],True,None),page([],more='false'),
])
def test_error_or_malformed_response_fails_closed(monkeypatch,response):
    (result,code),_=adapter(monkeypatch,[response])
    assert code!=0 and result['verdict']=='fail'
    assert 'data' not in result


def test_repeated_cursor_or_page_limit_fails_closed(monkeypatch):
    for responses in ([page([],True,'same')],[page([],True,str(i)) for i in range(20)]):
        (result,code),calls=adapter(monkeypatch,responses)
        assert code!=0 and result['verdict']=='fail'
        assert len(calls)<=20


@pytest.mark.parametrize('thread_envelope',[
    {'verdict':'fail','reason':'auth-denied'}, {'verdict':'degraded'},
    {'verdict':'ok','data':{}}, {'verdict':'ok','data':{'unresolved':0,'actionable':-1}},
    {'verdict':'ok','data':{'unresolved':0,'actionable':1}},
    {'verdict':'ok','data':{'unresolved':False,'actionable':False}},
    {'verdict':'ok','data':{'unresolved':'0','actionable':'0'}},
    {'verdict':'ok','data':{'unresolved':2,'actionable':2}},
    {'verdict':'ok','data':{'unresolved':0,'actionable':0}},
])
def test_check_gate_never_green_without_valid_zero_threads(tmp_path,monkeypatch,thread_envelope):
    def host(root,*args):
        if args[0]=='pr-view':return {'verdict':'ok','data':{'headRefOid':HEAD,'mergeable':'MERGEABLE','mergeStateStatus':'CLEAN'}}
        if args[0]=='repo-meta':return {'verdict':'ok','data':{'nameWithOwner':'grdavies/tierforge'}}
        if args[0]=='review-threads':return thread_envelope
        raise AssertionError(args)
    monkeypatch.setattr(gate,'host_verb',host)
    monkeypatch.setattr('host_lib.resolve_provider',lambda root:{'verdict':'ok','provider':'github'})
    monkeypatch.setattr(gate,'load_workflow_config',lambda root:{'review':{'provider':'none'}})
    monkeypatch.setattr(gate,'resolve_checks_evidence_for_gate',lambda *a,**k:{'evidenceValidity':'valid','checks':[{'name':'unit','state':'SUCCESS'}]})
    monkeypatch.setattr(gate,'resolve_review_state',lambda *a,**k:({'error':False,'review_provider':'none','cr_state':'off','cr_landed':True,'cr_reviewed_head':'','cr_status':'off','cr_marker':False,'cr_skipped':False,'mins_since':0,'review_landed':True,'review_state':'off'},[]))
    code,result=gate.run_gate(tmp_path,'351')
    if thread_envelope == {'verdict':'ok','data':{'unresolved':0,'actionable':0}} and type(thread_envelope['data']['unresolved']) is int:
        assert code == 0 and result['verdict'] == 'green'
        return
    assert code!=0 and result['verdict']!='green'
    if thread_envelope.get('data',{}).get('unresolved')==2:
        assert result['unresolvedActionable']==2
    else:
        assert result['verdict']=='blocked'
        assert result['reasonCode']=='review-threads-invalid'


def test_complete_empty_connection_is_valid(monkeypatch):
    (result, code), _ = adapter(monkeypatch, [page([])])
    assert code == 0 and result['data'] == {'unresolved': 0, 'actionable': 0}


@pytest.mark.parametrize('status', [401, 403, 500])
def test_transport_failure_is_not_zero_threads(monkeypatch, status):
    monkeypatch.setattr(github.common, 'mock_fixture', lambda *a: None)
    monkeypatch.setattr(github.common, 'http_request', lambda **k: {
        'verdict': 'fail', 'statusCode': status, 'body': '{}'})
    result, code = github._review_threads(Path('/tmp'), CTX, ['--number', '351'])
    assert code != 0 and result['verdict'] != 'ok'

"""L3 R9: offline trust/durability tests for LAN reconciliation. No network/filesystem writes."""
import hashlib
import json
import pytest
from rai_fabric.p2p_lan_sync import CrossHostP2PSyncManager


def _offer(name, payload):
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {'protocol': 'BPR5_NEXTGEN_R3.3', 'stage': 'STAGE_R28_P2P_MERKLE',
            'node_id': 'remote', 'merkle_root': 'different-declared-root',
            'items_manifest': {name: digest}, 'checkpoints_count': 1, 'timestamp': 123}


@pytest.mark.parametrize('bad_path', ['../escape.json', r'..\secret.json', '/etc/passwd', 'C:\\abs.json', 'sub/dir.json', ''])
def test_malicious_checkpoint_path_never_reaches_fetch_callback(tmp_path,bad_path):
    m=CrossHostP2PSyncManager(repo_root=tmp_path, node_id='local')
    calls=[]
    def get_checkpoint(name):
        calls.append(name)
        return {'v':1}
    result=m.reconcile_with_peer(_offer(bad_path, {'v':1}), fetch_checkpoint_fn=get_checkpoint)
    assert result['status']=='DIVERGENT'
    assert calls==[]
    assert result['errors']
    assert result.get('applied_to_local_store') is False


def test_reconcile_fetch_exception_is_bounded_failure(tmp_path):
    m=CrossHostP2PSyncManager(repo_root=tmp_path)
    def broken(_):
        raise OSError('synthetic remote failure')
    result=m.reconcile_with_peer(_offer('safe.json', {'v':1}), fetch_checkpoint_fn=broken)
    assert result['status']=='DIVERGENT'
    assert result['errors']
    assert result['reconciled_items']==[]


def test_reconcile_non_dict_checkpoint_cannot_be_accepted(tmp_path):
    m=CrossHostP2PSyncManager(repo_root=tmp_path)
    data='text not a structured checkpoint'
    result=m.reconcile_with_peer(_offer('safe.json', data), fetch_checkpoint_fn=lambda name: data)
    assert result['status']=='DIVERGENT'
    assert result['reconciled_items']==[]


def test_reconcile_valid_hash_is_only_in_memory_not_durable(tmp_path):
    m=CrossHostP2PSyncManager(repo_root=tmp_path)
    payload={'valid':True,'version':'1'}
    result=m.reconcile_with_peer(_offer('safe.json', payload),fetch_checkpoint_fn=lambda name:payload)
    assert result['status']=='RECONCILED'  # historical status compatibility
    assert result['applied_to_local_store'] is False
    assert result['origin_authenticated'] is False
    assert result['evidence_grade']=='IN_MEMORY_HASH_MATCH_ONLY'
    assert not (tmp_path/'checkpoints'/'safe.json').exists()


def test_matching_offer_is_not_an_authenticated_receipt(tmp_path):
    m=CrossHostP2PSyncManager(repo_root=tmp_path)
    offer=m.exchange.create_sync_offer(node_id='other')
    result=m.reconcile_with_peer(offer)
    assert result['status']=='IN_SYNC'
    assert result['origin_authenticated'] is False
    assert result['evidence_grade']=='SELF_DECLARED_OFFER_ONLY'
    assert result['applied_to_local_store'] is False


def test_malformed_remote_offer_fails_closed_without_exception(tmp_path):
    m=CrossHostP2PSyncManager(repo_root=tmp_path)
    result=m.reconcile_with_peer(['not a mapping'])
    assert result['status']=='DIVERGENT'
    assert result['is_parity'] is False
    assert result['errors']
    assert result['applied_to_local_store'] is False


def test_topology_advertised_root_is_unverified_hint(tmp_path):
    m=CrossHostP2PSyncManager(repo_root=tmp_path)
    own_root=m.exchange.create_sync_offer()['merkle_root']
    m.discovery.register_synthetic_peer({'node_id':'self_declared', 'merkle_root':own_root,'ttl_seconds':10})
    snapshot=m.get_fleet_lan_topology()
    remote=[p for p in snapshot['nodes'] if not p['is_self']][0]
    assert remote['origin_authenticated'] is False
    assert remote['parity_evidence']=='REMOTE_ROOT_HINT_ONLY'


def test_partial_remote_validation_cannot_hide_divergent_local_checkpoint(tmp_path):
    from rai_fabric.tri_tower_sync import calculate_merkle_root
    cp=tmp_path/'checkpoints'; cp.mkdir()
    (cp/'existing.json').write_text(json.dumps({'v':'LOCAL'}),encoding='utf8')
    remote_existing={'v':'REMOTE'}
    new_item={'v': 'NEW'}
    items={
        'existing.json':hashlib.sha256(json.dumps(remote_existing,sort_keys=True).encode()).hexdigest(),
        'new.json':hashlib.sha256(json.dumps(new_item,sort_keys=True).encode()).hexdigest(),
    }
    remote={'merkle_root':calculate_merkle_root(list(items.values())),
            'items_manifest':items,'node_id':'remote'}
    m=CrossHostP2PSyncManager(repo_root=tmp_path)
    got=m.reconcile_with_peer(remote,fetch_checkpoint_fn=lambda name:new_item)
    assert 'existing.json' in got['diff']['divergent_files']
    assert got['reconciled_items']==['new.json']
    assert got['status']=='DIVERGENT'
    assert got['applied_to_local_store'] is False


def test_partial_remote_validation_cannot_hide_extra_local_checkpoint(tmp_path):
    from rai_fabric.tri_tower_sync import calculate_merkle_root
    cp=tmp_path/'checkpoints'; cp.mkdir()
    (cp/'extra.json').write_text(json.dumps({'v':'LOCAL'}),encoding='utf8')
    new_item={'v':'NEW'}
    digest=hashlib.sha256(json.dumps(new_item,sort_keys=True).encode()).hexdigest()
    remote={'merkle_root':calculate_merkle_root([digest]),
            'items_manifest':{'new.json':digest},'node_id':'remote'}
    m=CrossHostP2PSyncManager(repo_root=tmp_path)
    result=m.reconcile_with_peer(remote,fetch_checkpoint_fn=lambda name:new_item)
    assert 'extra.json' in result['diff']['missing_in_remote']
    assert result['reconciled_items']==['new.json']
    assert result['status']=='DIVERGENT'

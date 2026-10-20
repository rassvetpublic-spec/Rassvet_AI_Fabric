"""L3 R8 offline negatives: exact root, duplicate leaves, false parity and malformed proofs."""
import hashlib
import pytest
from rai_fabric.p2p_merkle import P2PMerkleExchange
from rai_fabric.tri_tower_sync import calculate_merkle_root


def _d(ch: str) -> str:
    return ch * 64


def test_proof_uses_canonical_value_sort_order(tmp_path):
    exchange = P2PMerkleExchange(repo_root=tmp_path)
    # Filename order intentionally differs from sorted hash order.
    items = {'alpha.json': _d('f'), 'beta.json': _d('1'), 'gamma.json': _d('a')}
    root = calculate_merkle_root(list(items.values()))
    for name in items:
        proof = exchange.generate_merkle_proof(name, items)
        assert proof is not None
        assert proof['checkpoint_name'] == name
        assert proof['merkle_root'] == root
        assert exchange.verify_merkle_proof(proof['file_hash'], proof['proof_path'], root)


def test_duplicate_hash_selects_named_leaf_position(tmp_path):
    exchange = P2PMerkleExchange(repo_root=tmp_path)
    items = {'first.json': _d('f'), 'second.json': _d('f'), 'earlier.json': _d('0')}
    proof_first = exchange.generate_merkle_proof('first.json', items)
    proof_second = exchange.generate_merkle_proof('second.json', items)
    assert proof_first is not None and proof_second is not None
    assert proof_first['proof_path'][0]['direction'] == 'left'
    assert proof_second['proof_path'][0]['direction'] == 'right'
    root = calculate_merkle_root(list(items.values()))
    assert proof_first['merkle_root'] == proof_second['merkle_root'] == root
    # This is hash inclusion, NOT cryptographic filename identity.


def test_same_claimed_root_but_different_manifest_is_not_parity(tmp_path):
    exchange = P2PMerkleExchange(repo_root=tmp_path)
    # Renaming a file does not affect current Merkle root (leaf names are unbound).
    a = {'a.json': _d('1'), 'b.json': _d('f')}
    b = {'a.json': _d('1'), 'renamed.json': _d('f')}
    root = calculate_merkle_root(list(a.values()))
    result = exchange.compare_offers({'merkle_root': root, 'items_manifest': a},
                                     {'merkle_root': root, 'items_manifest': b})
    assert result['is_parity'] is False
    assert result['needs_sync'] is True
    assert result['missing_in_remote'] == ['b.json']
    assert result['missing_in_local'] == ['renamed.json']


def test_identical_but_fabricated_merkle_root_is_not_parity(tmp_path):
    exchange = P2PMerkleExchange(repo_root=tmp_path)
    items = {'x.json': _d('3'), 'y.json': _d('4')}
    fake = _d('e')
    result = exchange.compare_offers({'merkle_root': fake, 'items_manifest': items},
                                     {'merkle_root': fake, 'items_manifest': items})
    assert result['is_parity'] is False
    assert result['needs_sync'] is True


def test_reject_malformed_merkle_proof_step_direction(tmp_path):
    exchange = P2PMerkleExchange(repo_root=tmp_path)
    items = {'a.json': _d('1'), 'b.json': _d('2')}
    proof = exchange.generate_merkle_proof('b.json', items)
    assert proof and proof['proof_path'][0]['direction'] == 'left'
    tampered = [dict(x) for x in proof['proof_path']]
    tampered[0]['direction'] = 'UNRECOGNIZED'
    assert exchange.verify_merkle_proof(proof['file_hash'], tampered, proof['merkle_root']) is False
    assert exchange.verify_merkle_proof(proof['file_hash'], None, proof['merkle_root']) is False


def test_existing_happy_path_not_regressed(tmp_path):
    exchange = P2PMerkleExchange(repo_root=tmp_path)
    cp = tmp_path / 'checkpoints'
    cp.mkdir()
    (cp/'a.json').write_text('{"v":1}')
    (cp/'b.json').write_text('{"v":2}')
    offer1 = exchange.create_sync_offer(node_id='one')
    offer2 = exchange.create_sync_offer(node_id='two')
    assert exchange.compare_offers(offer1,offer2)['is_parity'] is True
    for filename, digest in offer1['items_manifest'].items():
        proof = exchange.generate_merkle_proof(filename,offer1['items_manifest'])
        assert proof['merkle_root']==offer1['merkle_root']
        assert exchange.verify_merkle_proof(digest,proof['proof_path'],offer1['merkle_root'])


def test_still_detects_differing_roots_without_fake_parity(tmp_path):
    exchange = P2PMerkleExchange(repo_root=tmp_path)
    a={'f1.json':_d('1'),'f2.json':_d('2')}
    b={'f1.json':_d('1'),'f2.json':_d('3')}
    result=exchange.compare_offers({'merkle_root':calculate_merkle_root(list(a.values())),'items_manifest':a},
                                   {'merkle_root':calculate_merkle_root(list(b.values())),'items_manifest':b})
    assert not result['is_parity'] and result['divergent_files']==['f2.json']

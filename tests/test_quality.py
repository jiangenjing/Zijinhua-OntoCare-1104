def test_quality_routes_and_download_allowlist(app):
    client=app.test_client()
    assert client.get('/quality').status_code==200
    assert client.get('/api/quality/cases?arm=../../local').status_code==400
    assert client.get('/api/quality/cases?page=invalid').status_code==400
    assert client.get('/api/quality/download/private-key').status_code==404
    assert client.get('/api/quality/cases?arm=release').json['total']==0

"""Small, repeatable read-only origin benchmark for local/staging development.

This is not a 100,000-user capacity certificate. Keep production benchmarking
separate, at an agreed request rate and with CDN/database observability.
"""
import argparse
import json
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def benchmark(url, requests=100, concurrency=12):
    def fetch(_):
        start=time.perf_counter()
        try:
            with urlopen(url,timeout=15) as response:
                body=response.read()
                status=response.status
        except HTTPError as error:
            status=error.code;body=error.read()
        except (URLError,TimeoutError):
            status='connection_error';body=b''
        return status,time.perf_counter()-start,len(body)
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        outcomes=list(executor.map(fetch,range(requests)))
    elapsed=time.perf_counter()-start
    latencies=sorted(row[1]*1000 for row in outcomes)
    return {'url':url,'requests':requests,'concurrency':concurrency,
            'elapsed_seconds':round(elapsed,3),'requests_per_second':round(requests/elapsed,2),
            'status_counts':dict(Counter(str(row[0]) for row in outcomes)),
            'latency_ms':{'p50':round(statistics.median(latencies),2),
                          'p95':round(latencies[max(0,int(len(latencies)*.95)-1)],2),
                          'max':round(max(latencies),2)},
            'response_bytes':sum(row[2] for row in outcomes),
            'scope':'Origin only; no CDN or distributed traffic. Does not certify concurrent-user capacity.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8000/api/news?limit=30')
    parser.add_argument('--requests',type=int,default=100)
    parser.add_argument('--concurrency',type=int,default=12)
    args=parser.parse_args()
    if urlsplit(args.url).hostname not in {'localhost','127.0.0.1'}:
        raise SystemExit('This local benchmark does not generate remote traffic.')
    if not 1<=args.requests<=10000 or not 1<=args.concurrency<=64:
        raise SystemExit('Use 1–10000 requests and 1–64 connections.')
    print(json.dumps(benchmark(args.url,args.requests,args.concurrency),indent=2))

#!/bin/sh
# Every 4 hours (launchd com.ticketpriceresearch.feed): Discovery Feed (1 call) then the final-week price pass
# (~20-30 calls). Both are budgeted by forward_collector's rolling 24 h counter.
cd "$(dirname "$0")/.." || exit 1
.venv/bin/python forward_collector.py feed
.venv/bin/python forward_collector.py near

from collections import OrderedDict
from datetime import datetime, timedelta

from influxdb import InfluxDBClient
from maya import MayaDT


class InfluxCrawlerClient:
    """
    Performs operations on data in the MoeBlockchainCrawler DB.

    Helpful for data intensive long-running graphing calculations on historical data.
    """
    def __init__(self, host, port, database):
        self._client = InfluxDBClient(host=host, port=port, database=database)

    def get_historical_locked_tokens_over_range(self, days: int):
        today = datetime.utcnow()
        range_end = datetime(year=today.year, month=today.month, day=today.day,
                             hour=0, minute=0, second=0, microsecond=0)
        range_begin = range_end - timedelta(days=days-1)
        results = list(self._client.query(f"SELECT SUM(locked_stake) "
                                          f"FROM ("
                                          f"SELECT staker_address, current_period, "
                                          f"LAST(locked_stake) "
                                          f"AS locked_stake "
                                          f"FROM moe_network_info "
                                          f"WHERE time >= '{MayaDT.from_datetime(range_begin).rfc3339()}' "
                                          f"AND "
                                          f"time < '{MayaDT.from_datetime(range_end + timedelta(days=1)).rfc3339()}' "
                                          f"GROUP BY staker_address, time(1d)"
                                          f") "
                                          f"GROUP BY time(1d)").get_points())

        # Note: all days may not have values eg. days before DB started getting populated
        # As time progresses this should be less of an issue
        locked_tokens_dict = OrderedDict()
        for r in results:
            locked_stake = r['sum']
            if locked_stake:
                # Dash accepts datetime objects for graphs
                locked_tokens_dict[MayaDT.from_rfc3339(r['time']).datetime()] = locked_stake

        return locked_tokens_dict

    def get_historical_num_stakers_over_range(self, days: int):
        today = datetime.utcnow()
        range_end = datetime(year=today.year, month=today.month, day=today.day,
                             hour=0, minute=0, second=0, microsecond=0)
        range_begin = range_end - timedelta(days=days - 1)
        results = list(self._client.query(f"SELECT COUNT(staker_address) FROM "
                                          f"("
                                            f"SELECT staker_address, LAST(locked_stake)"
                                            f"FROM moe_network_info WHERE "
                                            f"time >= '{MayaDT.from_datetime(range_begin).rfc3339()}' AND "
                                            f"time < '{MayaDT.from_datetime(range_end + timedelta(days=1)).rfc3339()}' "
                                            f"GROUP BY staker_address, time(1d)"
                                          f") "
                                          "GROUP BY time(1d)").get_points())   # 1 day measurements

        # Note: all days may not have values eg. days before DB started getting populated
        # As time progresses this should be less of an issue
        num_stakers_dict = OrderedDict()
        for r in results:
            locked_stake = r['count']
            if locked_stake:
                # Dash accepts datetime objects for graphs
                num_stakers_dict[MayaDT.from_rfc3339(r['time']).datetime()] = locked_stake

        return num_stakers_dict

    def close(self):
        self._client.close()
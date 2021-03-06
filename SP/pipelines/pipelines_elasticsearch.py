#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @Time : 2020/6/1 17:16
# @Author : way
# @Site : 
# @Describe: 基础类，数据入库 elasticsearch

import time
import logging
from elasticsearch import Elasticsearch, helpers
from SP.utils.make_key import rowkey, bizdate

logger = logging.getLogger(__name__)


class ElasticSearchPipeline(object):

    def __init__(self, **kwargs):
        self.table_cols_map = {}  # 表字段顺序 {table：(cols, col_default)}
        self.bizdate = bizdate  # 业务日期为启动爬虫的日期
        self.buckets_map = {}  # 桶 {table：items}
        self.bucketsize = kwargs.get('BUCKETSIZE')
        self.ES = Elasticsearch(kwargs.get('ES_SERVERS'))

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(**settings)

    def process_item(self, item, spider):
        """
        :param item:
        :param spider:
        :return: 数据分表入库
        """
        if item.tablename in self.buckets_map:
            self.buckets_map[item.tablename].append(item)
        else:
            cols, col_default = [], {}
            for field, value in item.fields.items():
                cols.append(field)
                col_default[field] = item.fields[field].get('default', '')
            cols.sort(key=lambda x: item.fields[x].get('idx', 1))
            self.table_cols_map.setdefault(item.tablename, (cols, col_default))  # 定义表结构、字段顺序、默认值
            self.buckets_map.setdefault(item.tablename, [item])
        self.buckets2db(bucketsize=self.bucketsize, spider_name=spider.name)  # 将满足条件的桶 入库
        return item

    def close_spider(self, spider):
        """
        :param spider:
        :return:  爬虫结束时，将桶里面剩下的数据 入库
        """
        self.buckets2db(bucketsize=1, spider_name=spider.name)

    def buckets2db(self, bucketsize=100, spider_name=''):
        """
        :param bucketsize:  桶大小
        :param spider_name:  爬虫名字
        :return: 遍历每个桶，将满足条件的桶，入库并清空桶
        """
        for tablename, items in self.buckets_map.items():  # 遍历每个桶，将满足条件的桶，入库并清空桶
            if len(items) >= bucketsize:
                actions = []
                cols, col_default = self.table_cols_map.get(tablename)
                for item in items:
                    new_item = {}
                    for field in cols:
                        new_item[field] = item.get(field, col_default.get(field))
                    new_item['bizdate'] = self.bizdate  # 增加非业务字段
                    new_item['ctime'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    new_item['spider'] = spider_name
                    action = {'_op_type': 'index',  # 操作 index update create delete  
                              '_index': spider_name,  # index
                              '_id': rowkey(),
                              '_type': tablename,  # type
                              '_source': new_item}
                    actions.append(action)
                try:
                    helpers.bulk(self.ES, actions=actions)
                    logger.info(f"入库成功 <= 索引：{spider_name}, 类型:{tablename} 记录数:{len(items)}")
                    items.clear()  # 清空桶
                except Exception as e:
                    logger.error(f"入库失败 <= 索引：{spider_name}, 类型:{tablename} 错误原因:{e}")

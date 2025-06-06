# -*- coding: UTF-8 -*-
"""
@author: hhyo
@license: Apache Licence
@file: sql_analyze.py
@time: 2019/03/14
"""
from pathlib import Path

import simplejson as json
from django.contrib.auth.decorators import permission_required
from django.core.files.temp import NamedTemporaryFile

from common.config import SysConfig
from sql.plugins.soar import Soar
from sql.utils.resource_group import user_instances
from sql.utils.sql_utils import generate_sql
from django.http import HttpResponse, JsonResponse
from common.utils.extend_json_encoder import ExtendJSONEncoder
from .models import Instance

__author__ = "hhyo"


@permission_required("sql.sql_analyze", raise_exception=True)
def generate(request):
    """
    解析上传文件为SQL列表
    :param request:
    :return:
    """
    text = request.POST.get("text")
    if text is None:
        result = {"total": 0, "rows": []}
    else:
        rows = generate_sql(text)
        result = {"total": len(rows), "rows": rows}
    return HttpResponse(
        json.dumps(result, cls=ExtendJSONEncoder, bigint_as_string=True),
        content_type="application/json",
    )


@permission_required("sql.sql_analyze", raise_exception=True)
def analyze(request):
    """
    利用soar分析SQL
    :param request:
    :return:
    """
    text = request.POST.get("text")
    instance_name = request.POST.get("instance_name")
    db_name = request.POST.get("db_name")
    if not text:
        result = {"total": 0, "rows": []}
    else:
        soar = Soar()
        if instance_name != "" and db_name != "":
            try:
                instance = user_instances(request.user, db_type=["mysql"]).get(
                    instance_name=instance_name
                )
            except Instance.DoesNotExist:
                return JsonResponse(
                    {"status": 1, "msg": "你所在组未关联该实例！", "data": []}
                )
            soar_test_dsn = SysConfig().get("soar_test_dsn")
            # 获取实例连接信息
            user, password = instance.get_username_password()
            online_dsn = f"{user}:{password}@{instance.host}:{instance.port}/{db_name}"
        else:
            online_dsn = ""
            soar_test_dsn = ""
        args = {
            "report-type": "markdown",
            "query": "",
            "online-dsn": online_dsn,
            "test-dsn": soar_test_dsn,
            "allow-online-as-test": False,
        }
        rows = generate_sql(text)
        for row in rows:
            # 验证是不是传过来的文件, 如果是文件, 报错
            try:
                p = Path(row["sql"].strip())
                if p.exists():
                    return JsonResponse(
                        {"status": 1, "msg": "SQL 语句不合法", "data": []}
                    )
            except OSError:
                pass
            args["query"] = row["sql"]
            cmd_args = soar.generate_args2cmd(args=args)
            stdout, stderr = soar.execute_cmd(cmd_args).communicate()
            row["report"] = stdout if stdout else stderr
        result = {"total": len(rows), "rows": rows}
    return HttpResponse(
        json.dumps(result, cls=ExtendJSONEncoder, bigint_as_string=True),
        content_type="application/json",
    )

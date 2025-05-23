# -*- coding: UTF-8 -*-
"""
@author: hhyo
@license: Apache Licence
@file: sql_utils.py
@time: 2019/03/13
"""
import re
import xml
import mybatis_mapper2sql
import sqlparse

from sql.engines.models import SqlItem
from sql.utils.extract_tables import extract_tables as extract_tables_by_sql_parse

__author__ = "hhyo"


def get_syntax_type(sql, parser=True, db_type="mysql"):
    """
    返回SQL语句类型，仅判断DDL和DML
    :param sql:
    :param parser: 是否使用sqlparse解析
    :param db_type: 不使用sqlparse解析时需要提供该参数
    :return:
    """
    sql = remove_comments(sql=sql, db_type=db_type)
    if parser:
        try:
            statement = sqlparse.parse(sql)[0]
            syntax_type = statement.token_first(skip_cm=True).ttype.__str__()
            if syntax_type == "Token.Keyword.DDL":
                syntax_type = "DDL"
            elif syntax_type == "Token.Keyword.DML":
                syntax_type = "DML"
        except Exception:
            syntax_type = None
    else:
        if db_type == "mysql":
            ddl_re = r"^alter|^create|^drop|^rename|^truncate"
            dml_re = r"^call|^delete|^do|^handler|^insert|^load\s+data|^load\s+xml|^replace|^select|^update"
        elif db_type == "oracle":
            ddl_re = r"^alter|^create|^drop|^rename|^truncate"
            dml_re = r"^delete|^exec|^insert|^select|^update|^with|^merge"
        else:
            # TODO 其他数据库的解析正则
            return None
        if re.match(ddl_re, sql, re.I):
            syntax_type = "DDL"
        elif re.match(dml_re, sql, re.I):
            syntax_type = "DML"
        else:
            syntax_type = None
    return syntax_type


def remove_comments(sql, db_type="mysql"):
    """
    去除SQL语句中的注释信息
    来源:https://stackoverflow.com/questions/35647841/parse-sql-file-with-comments-into-sqlite-with-python
    :param sql:
    :param db_type:
    :return:
    """
    sql_comments_re = {
        "oracle": [r"(?:--)[^\n]*\n", r"(?:\W|^)(?:remark|rem)\s+[^\n]*\n"],
        "mysql": [r"(?:#|--\s)[^\n]*\n"],
    }
    specific_comment_re = sql_comments_re[db_type]
    additional_patterns = "|"
    if isinstance(specific_comment_re, str):
        additional_patterns += specific_comment_re
    elif isinstance(specific_comment_re, list):
        additional_patterns += "|".join(specific_comment_re)
    pattern = r"(\".*?\"|\'.*?\')|(/\*.*?\*/{})".format(additional_patterns)
    regex = re.compile(pattern, re.MULTILINE | re.DOTALL)

    def _replacer(match):
        if match.group(2):
            return ""
        else:
            return match.group(1)

    return regex.sub(_replacer, sql).strip()


def extract_tables(sql):
    """
    获取sql语句中的库、表名
    :param sql:
    :return:
    """
    tables = list()
    for i in extract_tables_by_sql_parse(sql):
        tables.append(
            {
                "schema": i.schema,
                "name": i.name,
            }
        )
    return tables


def generate_sql(text):
    """
    从SQL文本、MyBatis3 Mapper XML file文件中解析出sql 列表
    :param text:
    :return: [{"sql_id": key, "sql": soar.compress(value)}]
    """
    # 尝试XML解析
    try:
        mapper, xml_raw_text = mybatis_mapper2sql.create_mapper(xml_raw_text=text)
        statements = mybatis_mapper2sql.get_statement(mapper, result_type="list")
        rows = []
        # 压缩SQL语句，方便展示
        for statement in statements:
            for key, value in statement.items():
                row = {"sql_id": key, "sql": value}
                rows.append(row)
    except xml.etree.ElementTree.ParseError:
        # 删除注释语句
        text = sqlparse.format(text, strip_comments=True)
        statements = sqlparse.split(text)
        rows = []
        num = 0
        for statement in statements:
            num = num + 1
            row = {"sql_id": num, "sql": statement}
            rows.append(row)
    return rows


def get_base_sqlitem_list(full_sql):
    """把参数 full_sql 转变为 SqlItem列表
    :param full_sql: 完整sql字符串, 每个SQL以分号;间隔, 不包含plsql执行块和plsql对象定义块
    :return: SqlItem对象列表
    """
    list = []
    for statement in sqlparse.split(full_sql):
        statement = sqlparse.format(
            statement, strip_comments=True, reindent=True, keyword_case="lower"
        )
        if len(statement) <= 0:
            continue
        item = SqlItem(statement=statement)
        list.append(item)
    return list


def get_full_sqlitem_list(full_sql, db_name):
    """获取Sql对应的SqlItem列表, 包括PLSQL部分
    :param full_sql: 全部sql内容
    :return: SqlItem 列表
    """

    """预处理SQL文本，第一步：自动添加PLSQL块结尾标识符
    根据PLSQL书写语法，识别结尾符号，在PLSQL语句结尾添加$$符号（单独一行），作为该平台处理PLSQL块结尾标识符
    同时需要过滤掉PLSQL块中间可能存在的注释 /* 注释内容 */ 干扰
    """
    pattern = r"(;(\s)*\n(/$|/\s))"
    full_sql = re.sub(pattern, ";\n/\n$$", full_sql, flags=re.I)

    """预处理SQL文本，第二步：自动添加PLSQL块开始标识符
    根据PLSQL书写语法，识别开始符号，在PLSQL语句开始前添加delimiter $$符号（单独一行），作为该平台处理PLSQL块开始标识符
    PLSQL块包括：以declare开始的匿名块、以begin开始的匿名块、存储过程、函数、触发器、包以及包体、对象类型以及对象类型体
    """

    """1、调整PLSQL开始部分语句，对于开始部分（如：create or replace procedure）中间可能存在换行的调整为一行，
    保证下一步处理中，使用换行分割时，PLSQL开始标识完整的落在一行内
    """
    pattern_dict = {
        r"(create\s+or\s+replace\s+procedure)": "create or replace procedure",
        r"(create\s+or\s+replace\s+function)": "create or replace function",
        r"(create\s+or\s+replace\s+trigger)": "create or replace trigger",
        r"(create\s+or\s+replace\s+package)": "create or replace package",
        r"(create\s+or\s+replace\s+type)": "create or replace type",
        r"(create\s+procedure)": "create procedure",
        r"(create\s+function)": "create function",
        r"(create\s+trigger)": "create trigger",
        r"(create\s+package)": "create package",
        r"(create\s+type)": "create type",
    }

    for pattern in pattern_dict:
        full_sql = re.sub(pattern, pattern_dict[pattern], full_sql, flags=re.I)

    """2、使用换行符分割SQL文本，逐行处理SQL文本：
    识别PLSQL开始语法标识符，在开始标识符前加delimiter $$（独立一行），作为该平台识别PLSQL开始位置的标识符，
    同时通过引入is_inside_plsqlblock参数，排除掉那些可能存在于PLSQL程序块内部的开始标识符（declare，begin,create [or replace] xx等）
    """
    pre_sql_list = full_sql.split("\n")
    full_sql_new = ""
    is_inside_plsqlblock = 0

    # 逐行处理SQL文本
    for line in pre_sql_list:
        # 匹配到declare和begin开始的行，同时该行SQL不是处于PLSQL程序块内部的，前面添加delimiter $$标识符（独立一行）
        pattern = r"^(declare|begin)"
        groups = re.match(pattern, line.lstrip(), re.IGNORECASE)
        if groups and is_inside_plsqlblock == 0:
            line = "delimiter $$" + "\n" + line
            # 修改is_inside_plsqlblock参数为1，标识文本进入PLSQL块内部
            is_inside_plsqlblock = 1

        # 匹配到create [or replace] function|procedure|trigger|package|type开始的行，同时该行SQL不是处于PLSQL程序块内部的，
        # 前面添加delimiter $$标识符（独立一行）
        pattern = (
            r"^create\s+(or\s+replace\s+)?(function|procedure|trigger|package|type)\s"
        )
        groups = re.match(pattern, line.lstrip(), re.IGNORECASE)
        if groups and is_inside_plsqlblock == 0:
            line = "delimiter $$" + "\n" + line
            # 修改is_inside_plsqlblock参数为1，标识文本进入PLSQL块内部
            is_inside_plsqlblock = 1

        # 匹配到内容为$$的行，修改is_inside_plsqlblock参数为0，标识文本跳出PLSQL块
        if line.strip() == "$$":
            is_inside_plsqlblock = 0
        full_sql_new = full_sql_new + line + "\n"

    list = []

    # 定义开始分隔符，两端用括号，是为了re.split()返回列表包含分隔符
    regex_delimiter = r"(delimiter\s*\$\$)"
    # 注意：必须把package body置于package之前，否则将永远匹配不上package body
    regex_objdefine = r'create\s+or\s+replace\s+(function|procedure|trigger|package\s+body|package|type\s+body|type)\s+("?\w+"?\.)?"?\w+"?[\s+|\(]'
    # 对象命名，两端有双引号
    regex_objname = r'^".+"$'

    sql_list = re.split(pattern=regex_delimiter, string=full_sql_new, flags=re.I)

    # delimiter_flag => 分隔符标记, 0:不是, 1:是
    # 遇到分隔符标记为1, 则本块SQL要去判断是否有PLSQL内容
    # PLSQL内容存在判定依据, 本块SQL包含'$$'

    delimiter_flag = 0
    for sql in sql_list:
        # 截去首尾空格和多余空字符
        sql = sql.strip()

        # 如果字符串长度为0, 跳过该字符串
        if len(sql) <= 0:
            continue

        # 表示这一行是分隔符, 跳过该字符串
        if re.match(regex_delimiter, sql):
            delimiter_flag = 1
            continue

        if delimiter_flag == 1:
            # 表示SQL块为delimiter $$标记之后的内容

            # 查找是否存在'$$'结束符
            pos = sql.find("$$")
            length = len(sql)
            if pos > -1:
                # 该sqlitem包含结束符$$
                # 处理PLSQL语句块, 这里需要先去判定语句块的类型
                plsql_block = sql[0:pos].strip()
                # 如果plsql_area字符串最后一个字符为/,则把/给去掉
                while True:
                    if plsql_block[-1:] == "/":
                        plsql_block = plsql_block[:-1].strip()
                    else:
                        break

                search_result = re.search(regex_objdefine, plsql_block, flags=re.I)

                # 检索关键字, 分为两个情况
                # 情况1：plsql block 为对象定义执行块
                # 情况2：plsql block 为匿名执行块

                if search_result:
                    # 检索到关键字, 属于情况1

                    str_plsql_match = search_result.group()
                    str_plsql_type = search_result.groups()[0]

                    idx = str_plsql_match.index(str_plsql_type)
                    nm_str = str_plsql_match[idx + len(str_plsql_type) :].strip()

                    if nm_str[-1:] == "(":
                        nm_str = nm_str[:-1]
                    nm_list = nm_str.split(".")

                    if len(nm_list) > 1:
                        # 带有属主的对象名, 形如object_owner.object_name

                        # 获取object_owner
                        if re.match(regex_objname, nm_list[0]):
                            # object_owner两端带有双引号
                            object_owner = nm_list[0].strip().strip('"')
                        else:
                            # object_owner两端不带有双引号
                            object_owner = nm_list[0].upper().strip().strip("'")

                        # 获取object_name
                        if re.match(regex_objname, nm_list[1]):
                            # object_name两端带有双引号
                            object_name = nm_list[1].strip().strip('"')
                        else:
                            # object_name两端不带有双引号
                            object_name = nm_list[1].upper().strip()
                    else:
                        # 不带属主
                        object_owner = db_name
                        if re.match(regex_objname, nm_list[0]):
                            # object_name两端带有双引号
                            object_name = nm_list[0].strip().strip('"')
                        else:
                            # object_name两端不带有双引号
                            object_name = nm_list[0].upper().strip()

                    tmp_object_type = str_plsql_type.upper()
                    tmp_stmt_type = "PLSQL"
                    if tmp_object_type == "VIEW":
                        tmp_stmt_type = "SQL"

                    item = SqlItem(
                        statement=plsql_block,
                        stmt_type=tmp_stmt_type,
                        object_owner=object_owner,
                        object_type=tmp_object_type,
                        object_name=object_name,
                    )
                    list.append(item)
                else:
                    # 未检索到关键字, 属于情况2, 匿名可执行块 it's ANONYMOUS
                    item = SqlItem(
                        statement=plsql_block.strip(),
                        stmt_type="PLSQL",
                        object_owner=db_name,
                        object_type="ANONYMOUS",
                        object_name="ANONYMOUS",
                    )
                    list.append(item)

                if length > pos + 2:
                    # 处理$$之后的那些语句, 默认为单条可执行SQL的集合
                    # 创建视图、序列、表，语句作为SQL处理最后如果加了 / ，预处理中会在 / 后一行加$$，
                    # 这里需要将SQL文本中 /\n$$ 去除后再传给get_base_sqlitem_list函数
                    sql_area = sql[pos + 2 :].replace("/\n$$", "").strip()
                    if len(sql_area) > 0:
                        tmp_list = get_base_sqlitem_list(sql_area)
                        list.extend(tmp_list)

            else:
                # 没有匹配到$$标记, 默认为单条可执行SQL集合
                tmp_list = get_base_sqlitem_list(sql)
                list.extend(tmp_list)

            # 处理完本次delimiter标记的内容，把delimiter_flag重置
            delimiter_flag = 0
        else:
            # 表示当前为以;结尾的正常sql
            # 创建视图、序列、表，语句作为SQL处理最后如果加了 / ，预处理中会在 / 后一行加$$，
            # 这里需要将SQL文本中 /\n$$ 去除后再传给get_base_sqlitem_list函数
            sql = sql.replace("/\n$$", "")
            tmp_list = get_base_sqlitem_list(sql)
            list.extend(tmp_list)
    return list


def get_exec_sqlitem_list(reviewResult, db_name):
    """根据审核结果生成新的SQL列表
    :param reviewResult: SQL审核结果列表
    :param db_name:
    :return:
    """
    list = []

    for item in reviewResult:
        list.append(
            SqlItem(
                statement=item["sql"],
                stmt_type=item["stmt_type"],
                object_owner=item["object_owner"],
                object_type=item["object_type"],
                object_name=item["object_name"],
            )
        )
    return list


def filter_db_list(db_list, db_name_regex: str, is_match_regex: bool, key="value"):
    """
    根据配置的数据库列表过滤数据库名称列表。

    :param db_list: 待过滤的数据库名称列表，可能是字符串列表或字典列表。
    示例数据：
    1. db_list=[{"value": 0, "text": 0, "value": 1, "text": 1}]
    2. db_list=["a_db","b_db"]
    :param db_name_regex: 配置的数据库正则。
    :param is_match_regex 是匹配还是不匹配的正则
    :param key: 当 db_list 包含字典时，指定用于匹配的键。默认值为 'value'。
    :return: 过滤后的数据库名称列表或字典列表。
    """
    if not db_name_regex:
        return db_list  # 如果没有指定 db_name_regex，返回原始 db_list

    try:
        db_regex = re.compile(db_name_regex)  # 编译正则表达式
    except re.error:
        raise ValueError(f"正则表达式解析异常: {db_name_regex}")

    filtered_list = []

    # 根据类型处理 db_list
    for db in db_list:
        # 确定要检查的值（字符串或字典中的特定键）
        db_value = str(db[key]) if isinstance(db, dict) else db
        is_match = bool(db_regex.match(db_value))
        # 根据 is_match_regex 参数过滤
        if (is_match_regex and is_match) or (not is_match_regex and not is_match):
            filtered_list.append(db)
    return filtered_list

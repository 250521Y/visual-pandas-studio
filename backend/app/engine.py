"""Allowlisted Pandas operations. No expression evaluation or executable project files."""
from __future__ import annotations

import io
import json
import math
import operator
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

AGGS = {"count", "sum", "mean", "median", "min", "max", "std", "nunique"}


class DataError(ValueError):
    def __init__(self, code: str, details: Any = None):
        self.code, self.details = code, details
        super().__init__(code)


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(value)
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def pack(df: pd.DataFrame) -> str:
    return json.dumps({"data": clean(df.to_dict("split")), "types": {c: str(t) for c, t in df.dtypes.items()}}, ensure_ascii=False, allow_nan=False)


def unpack(payload: str) -> pd.DataFrame:
    obj = json.loads(payload)
    # Preserve scalar types in object columns (e.g. exploded JSON integers + null).
    df = pd.DataFrame(**obj["data"],dtype=object)
    for col, dtype in obj["types"].items():
        if dtype.startswith("datetime"):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        else:
            try:
                df[col] = df[col].astype(dtype)
            except (ValueError, TypeError):
                pass
    return df


def table(df: pd.DataFrame, offset=0, limit=50):
    part = df.iloc[offset:offset + limit]
    return {"columns": list(df.columns), "rows": clean(part.to_dict("records")), "ids": clean(part.index.tolist()), "total": len(df), "offset": offset}


def kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_numeric_dtype(s):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    return "text"


def fields(df):
    result = []
    for c in df:
        s = df[c]
        k = kind(s)
        item = {"name": c, "type": k, "dtype": str(s.dtype), "count": int(s.count()), "missing": int(s.isna().sum()), "unique": int(s.nunique()), "missingRate": float(s.isna().mean()) if len(s) else 0}
        if k == "number":
            item.update(min=s.min(), max=s.max(), mean=s.mean(), std=s.std())
        elif k == "date":
            item.update(min=s.min(), max=s.max())
        item["frequencies"] = [{"value": clean(v), "count": int(n)} for v, n in s.value_counts().head(12).items()]
        result.append(clean(item))
    return result


def overview(df):
    cells = df.size
    missing = int(df.isna().sum().sum())
    duplicates = int(df.duplicated().sum()) if len(df.columns) else 0
    numbers = [c for c in df if kind(df[c]) == "number"]
    outliers = sum(int(outlier_mask(df[c], "iqr", {}).sum()) for c in numbers)
    return {"rows": len(df), "columns": len(df.columns), "numeric": len(numbers), "categorical": sum(kind(df[c]) == "text" for c in df), "missing": missing, "duplicates": duplicates, "memory": int(sum((df[c].where(df[c].notna(),None) if df[c].dtype==object else df[c]).memory_usage(index=False,deep=True) for c in df)+len(df)*8), "completeness": round(100 * (1 - missing / cells), 2) if cells else 100, "outliers": outliers, "quality": max(0, round(100 - (100 * missing / cells if cells else 0) - (100 * duplicates / len(df) if len(df) else 0), 1))}


def check_columns(df, columns):
    if not columns or any(c not in df for c in columns):
        raise DataError("invalid_field")


def numeric(df, c):
    check_columns(df, [c])
    if kind(df[c]) != "number":
        raise DataError("numeric_required")


def outlier_mask(s, method, p):
    if method == "iqr":
        q1, q3 = s.quantile([.25, .75])
        radius = float(p.get("threshold", 1.5)) * (q3 - q1)
        low, high = q1 - radius, q3 + radius
    elif method == "zscore":
        deviation = s.std(ddof=0)
        radius = float(p.get("threshold", 3)) * deviation
        low, high = s.mean() - radius, s.mean() + radius
    elif method == "custom":
        low, high = float(p["lower"]), float(p["upper"])
    else:
        raise DataError("invalid_method")
    if low > high:
        raise DataError("invalid_range")
    mask = (s < low) | (s > high)
    return (mask, low, high) if p.get("bounds") else mask


def convert(s, target):
    if target == "number":
        return pd.to_numeric(s, errors="coerce")
    if target == "date":
        return pd.to_datetime(s, errors="coerce", format="mixed")
    if target == "text":
        return s.astype("string")
    if target == "boolean":
        mapping = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False, "是": True, "否": False}
        return s.astype("string").str.lower().str.strip().map(mapping).astype("boolean")
    raise DataError("invalid_method")


def condition(df, cond):
    c, op = cond["field"], cond["operator"]
    check_columns(df, [c])
    s, v = df[c], cond.get("value")
    if op in {"isnull", "notnull"}:
        return s.isna() if op == "isnull" else s.notna()
    if op in {"contains", "startswith", "endswith"}:
        text = s.astype("string")
        if op == "contains":
            return text.str.contains(str(v), case=False, regex=False, na=False)
        return getattr(text.str, op)(str(v), na=False)
    if op == "in":
        values = v if isinstance(v, list) else str(v).split(",")
        if kind(s) == "number":
            values = [float(x) for x in values]
        elif kind(s) == 'date':
            values = [pd.to_datetime(x) for x in values]
        elif kind(s) == 'boolean':
            values = [boolean_filter_value(x) for x in values]
        return s.isin(values)
    if kind(s) == "number":
        v = float(v)
    elif kind(s) == "date":
        v = pd.to_datetime(v)
    elif kind(s) == "boolean":
        v = boolean_filter_value(v)
    ops = {"eq": operator.eq, "ne": operator.ne, "gt": operator.gt, "ge": operator.ge, "lt": operator.lt, "le": operator.le}
    if op not in ops:
        raise DataError("invalid_method")
    return ops[op](s, v).fillna(False)

def boolean_filter_value(value):
    text=str(value).strip().lower()
    if text not in {'true','false','1','0','yes','no','是','否'}:
        raise DataError('invalid_value')
    return text in {'true','1','yes','是'}


def apply_operation(df: pd.DataFrame, op: str, p: dict, other: pd.DataFrame | None = None, preview=False):
    result = df.copy(deep=True)
    warnings = []
    if op == "missing":
        cols, method = p["columns"], p["method"]
        check_columns(df, cols)
        if method == "drop_rows":
            result = result.dropna(subset=cols)
        elif method == "drop_columns":
            result = result.drop(columns=cols)
        else:
            for c in cols:
                s = result[c]
                if method in {"mean", "median"}:
                    numeric(result, c)
                    value = getattr(s, method)()
                    if pd.isna(value):
                        raise DataError("all_missing")
                    result[c] = s.astype(float).fillna(value)
                elif method == "mode":
                    modes = s.mode()
                    if modes.empty:
                        raise DataError("all_missing")
                    result[c] = s.fillna(modes.iloc[0])
                elif method == "constant":
                    v = p.get("value", "")
                    if kind(s) == "number":
                        v = float(v)
                    elif kind(s) == "date":
                        v = pd.to_datetime(v)
                    elif kind(s) == "boolean":
                        v = convert(pd.Series([v]), "boolean").iloc[0]
                        if pd.isna(v):
                            raise DataError("invalid_value")
                    result[c] = s.fillna(v)
                elif method in {"ffill", "bfill"}:
                    result[c] = getattr(s, method)()
                else:
                    raise DataError("invalid_method")
    elif op == "duplicates":
        cols = p.get("columns") or list(df.columns)
        check_columns(df, cols)
        keep = p.get("keep", "first")
        if keep not in {"first", "last", "none"}:
            raise DataError("invalid_method")
        result = result.drop_duplicates(subset=cols, keep=False if keep == "none" else keep)
    elif op == "type":
        c = p["field"]
        check_columns(df, [c])
        converted = convert(df[c], p["target"])
        failed = df[c].notna() & converted.isna()
        if failed.any():
            warnings = [{"code": "conversion_failed", "count": int(failed.sum()), "examples": clean(df.loc[failed, c].head(5).tolist())}]
            if not p.get("coerce", False) and not preview:
                raise DataError("conversion_failed", warnings[0])
        result[c] = converted
    elif op == "outliers":
        c = p["field"]
        numeric(df, c)
        mask, low, high = outlier_mask(df[c], p["method"], {**p, "bounds": True})
        action = p.get("action", "clip")
        if action == "drop":
            result = result.loc[~mask]
        elif action == "clip":
            result[c] = df[c].clip(low, high)
        else:
            raise DataError("invalid_method")
    elif op == "filter":
        conditions = p.get("conditions", [])
        if not conditions:
            raise DataError("invalid_value")
        masks = [condition(df, cond) for cond in conditions]
        mask = masks[0]
        for next_mask in masks[1:]:
            mask = mask | next_mask if p.get("logic") == "or" else mask & next_mask
        result = result.loc[mask]
    elif op == "sort":
        cols = p["columns"]
        check_columns(df, cols)
        ascending = p.get("ascending", True)
        if isinstance(ascending, list) and len(ascending) != len(cols):
            raise DataError("invalid_value")
        result = result.sort_values(cols, ascending=ascending, na_position=p.get("nulls", "last"), kind="stable")
    elif op == "column":
        action, c = p["action"], p.get("field")
        name = str(p.get("name", "")).strip()
        if action != "reorder":
            check_columns(df, [c])
        if action in {"rename", "copy", "calculate", "string", "date"}:
            if not name or name in df or len(name) > 100:
                raise DataError("invalid_name")
        if action == "rename":
            result = result.rename(columns={c: name})
        elif action == "drop":
            if len(df.columns) <= 1:
                raise DataError("last_column")
            result = result.drop(columns=[c])
        elif action == "copy":
            result[name] = df[c]
        elif action == "reorder":
            cols = p["columns"]
            if len(cols) != len(df.columns) or set(cols) != set(df.columns):
                raise DataError("invalid_field")
            result = result[cols]
        elif action == "calculate":
            numeric(df, c)
            if p.get("other"):
                numeric(df, p["other"])
                value = df[p["other"]]
            else:
                value = float(p.get("value", 1))
            ops = {"add": operator.add, "subtract": operator.sub, "multiply": operator.mul, "divide": operator.truediv}
            if p["method"] not in ops:
                raise DataError("invalid_method")
            result[name] = ops[p["method"]](df[c], value).replace([np.inf, -np.inf], np.nan)
        elif action == "string":
            s = df[c].astype("string")
            methods = {"lower", "upper", "strip", "len"}
            if p["method"] not in methods:
                raise DataError("invalid_method")
            result[name] = getattr(s.str, p["method"])()
        elif action == "date":
            s = pd.to_datetime(df[c], errors="coerce", format="mixed")
            if p["method"] not in {"year", "month", "day", "dayofweek"}:
                raise DataError("invalid_method")
            result[name] = getattr(s.dt, p["method"])
        else:
            raise DataError("invalid_method")
    elif op in {"group", "pivot"}:
        agg = p.get("agg", "mean")
        if agg not in AGGS:
            raise DataError("invalid_method")
        groups = p["groups"] if op == "group" else [p["row"]]
        values = p["values"] if op == "group" else [p["value"]]
        check_columns(df, groups + values + ([p["column"]] if op == "pivot" else []))
        if set(groups) & set(values):
            raise DataError("overlapping_fields")
        if agg in {"mean", "sum", "median", "std"}:
            for c in values:
                numeric(df, c)
        if op == "group":
            result = df.groupby(groups, dropna=False, observed=True)[values].agg(agg).reset_index()
        else:
            if p["row"] == p["column"] or p["value"] in {p["row"], p["column"]}:
                raise DataError("overlapping_fields")
            if df[p["row"]].nunique() * df[p["column"]].nunique() > 20000 or df[p["column"]].nunique() > 199:
                raise DataError("result_too_large")
            result = pd.pivot_table(df, index=p["row"], columns=p["column"], values=p["value"], aggfunc=agg, observed=True).reset_index()
            result.columns = [str(c) for c in result.columns]
        result.index = pd.RangeIndex(len(result))
    elif op in {"join", "concat"}:
        if other is None:
            raise DataError("invalid_dataset")
        if op == "join":
            left, right = p["left"], p["right"]
            check_columns(df, [left]); check_columns(other, [right])
            how = p.get("how", "left")
            if how not in {"inner", "left", "right", "outer"}:
                raise DataError("invalid_method")
            # Calculate potential cardinality before materializing a many-to-many merge.
            left_sizes=df.groupby(left,dropna=False).size().reset_index();left_sizes.columns=['key','left_count']
            right_sizes=other.groupby(right,dropna=False).size().reset_index();right_sizes.columns=['key','right_count']
            sizes=left_sizes.merge(right_sizes,on='key',how=how)
            estimated = int((sizes.left_count.fillna(1) * sizes.right_count.fillna(1)).sum())
            if estimated > 100000:
                raise DataError("result_too_large")
            result = df.merge(other, left_on=left, right_on=right, how=how, suffixes=("", "_right"))
        else:
            axis = int(p.get("axis", 0))
            if axis not in {0, 1}:
                raise DataError("invalid_method")
            if axis == 1:
                other = other.rename(columns={c: c + "_right" for c in other if c in df})
            result = pd.concat([df.reset_index(drop=True), other.reset_index(drop=True)], axis=axis, ignore_index=axis == 0)
        result.index = pd.RangeIndex(len(result))
    else:
        from .extensions import OPERATIONS, apply
        if op in OPERATIONS:
            result,warnings=apply(df,op,p,preview)
        else:
            from .reshape import OPERATIONS as RESHAPE, apply as reshape
            if op in RESHAPE:
                result,warnings=reshape(df,op,p)
            else:
                from .timeseries import OPERATIONS as TIME,apply as time_operation
                if op in TIME:
                    result,warnings=time_operation(df,op,p)
                else:
                    from .combination import OPERATIONS as COMBINATION, apply as combine
                    if op in COMBINATION:
                        result,warnings=combine(df,op,p,other)
                    else:
                        raise DataError("invalid_operation")
    if result.columns.duplicated().any():
        raise DataError("duplicate_columns")
    if not len(result.columns):
        raise DataError("last_column")
    if len(result) > 100000 or len(result.columns) > 200:
        raise DataError("result_too_large")
    for c in result:
        if kind(result[c])=='number':
            result[c]=result[c].mask(result[c].isin([np.inf,-np.inf]))
    if op=='join':
        from .combination import quality
        result.attrs['visual']={'quality':quality(df,other,p,len(result))}
    return result, warnings


def differences(before, after, aligned=True):
    common_rows = before.index.intersection(after.index) if aligned else pd.Index([])
    common_cols = before.columns.intersection(after.columns)
    changes = []
    if len(common_cols) and len(common_rows):
        a, b = before.loc[common_rows, common_cols], after.loc[common_rows, common_cols]
        equal = (a.astype(object).eq(b.astype(object)) | (a.isna() & b.isna())).fillna(False)
        coords = np.argwhere(~equal.to_numpy(dtype=bool))
        changes = [{"id": clean(common_rows[r]), "field": common_cols[c], "before": clean(a.iloc[r, c]), "after": clean(b.iloc[r, c])} for r, c in coords[:50]]
        count = len(coords)
    else:
        count = 0
    new_columns=after.columns.difference(before.columns).tolist()
    affected_fields=list(dict.fromkeys([common_cols[c] for _,c in coords] if len(common_cols) and len(common_rows) else []))+new_columns+before.columns.difference(after.columns).tolist()
    affected_ids=set(common_rows[r] for r,_ in coords) if len(common_cols) and len(common_rows) else set()
    removed=before.index.difference(after.index);added=after.index.difference(before.index)
    affected_ids.update(removed);affected_ids.update(added)
    if new_columns or len(before.columns.difference(after.columns)):affected_ids.update(after.index)
    if len(removed) or len(added):affected_fields=list(dict.fromkeys([*affected_fields,*before.columns,*after.columns]))
    if aligned and not len(removed) and not len(added) and not before.index.equals(after.index):
        moved=before.index.to_numpy()!=after.index.to_numpy()
        affected_ids.update(before.index[moved]);affected_ids.update(after.index[moved])
    affected_rows=len(affected_ids)
    if not aligned:
        affected_rows=len(before)
        affected_fields=list(dict.fromkeys([*before.columns,*after.columns]))
    return {"rowsBefore": len(before), "rowsAfter": len(after), "columnsBefore": len(before.columns), "columnsAfter": len(after.columns), "modifiedCells": count, "affectedFields":affected_fields,"affectedRows":affected_rows,"changes": changes, "deletedIds": clean(before.index.difference(after.index).tolist()[:100])}


def describe(df):
    rows = []
    for c in df:
        if kind(df[c]) != "number":
            continue
        s = df[c].dropna()
        rows.append(clean({"field": c, "count": len(s), "mean": s.mean(), "median": s.median(), "std": s.std(), "min": s.min(), "max": s.max(), "q1": s.quantile(.25), "q3": s.quantile(.75), "iqr": s.quantile(.75) - s.quantile(.25), "variance": s.var(), "skewness": s.skew(), "kurtosis": s.kurt()}))
    return rows


def chart(df, spec):
    typ, x, y = spec.get("type", "bar"), spec.get("x"), spec.get("y")
    check_columns(df, [x])
    color, size = spec.get("color") or spec.get("group"), spec.get("size")
    palette = ["#67B8B0", "#D999AC", "#8FAAC8", "#D4BA7F", "#9C94BC", "#89AC8A"]
    if typ in {"scatter", "bubble"}:
        numeric(df, x); numeric(df, y)
        if size:
            numeric(df, size)
        if color:
            check_columns(df, [color])
        sample = df.dropna(subset=[x, y]).head(5000)
        data = [{"id": int(i), "x": float(r[x]), "y": float(r[y]), "color": str(r[color]) if color else "", "size": clean(r[size]) if size else 1, "info": clean({c: r[c] for c in spec.get("tooltip", []) if c in df})} for i, r in sample.iterrows()]
        return {"type": typ, "points": data, "total": len(df), "sampled": len(df.dropna(subset=[x, y])) > 5000, "palette": palette}
    if typ in {"histogram", "box", "violin", "kde"}:
        numeric(df, x)
        group = spec.get("group") or color
        if group:
            check_columns(df, [group])
        groups = list(df.groupby(group, dropna=False, observed=True))[:30] if group else [(x, df)]
        data = []
        common_edges = np.histogram_bin_edges(df[x].dropna(), bins=max(3, min(60, int(spec.get('bins',15))))) if df[x].notna().any() else None
        for label, frame in groups:
            s = frame[x].dropna()
            if len(s) == 0:
                continue
            hist, edges = np.histogram(s, bins=common_edges)
            q1, median, q3 = s.quantile([.25, .5, .75])
            lower, upper = max(s.min(), q1 - 1.5 * (q3 - q1)), min(s.max(), q3 + 1.5 * (q3 - q1))
            valid = s[(s >= lower) & (s <= upper)]
            density = []
            if len(s) > 1 and s.std() > 0:
                grid = np.linspace(s.min(), s.max(), 80)
                # Density estimation uses a deterministic sample, summary statistics use all rows.
                kde = stats.gaussian_kde(s.iloc[np.linspace(0, len(s) - 1, min(len(s), 2000)).astype(int)])
                density = list(zip(grid.tolist(), kde(grid).tolist()))
            data.append(clean({"name": str(label), "hist": hist.tolist(), "edges": edges.tolist(), "box": [valid.min(), q1, median, q3, valid.max()], "outliers": s[(s < lower) | (s > upper)].head(500).tolist(), "density": density, "ids": clean(frame.index[:5000].tolist()), "mean": s.mean(), "std": s.std()}))
            if typ=='histogram':
                data[-1]['binIds']=[frame.index[(frame[x]>=edges[i]) & (frame[x]<=edges[i+1] if i==len(hist)-1 else frame[x]<edges[i+1])][:5000].tolist() for i in range(len(hist))]
        return {"type": typ, "groups": data, "palette": palette, "sampled": bool(group and df[group].nunique(dropna=False)>30)}
    if typ == "heatmap":
        numeric_cols = [c for c in df if kind(df[c]) == "number"]
        if not numeric_cols:
            raise DataError("numeric_required")
        method = spec.get("method", "pearson")
        if method=='values':
            numeric_cols=[c for c in numeric_cols if c!=x]
            if not numeric_cols:
                raise DataError('numeric_required')
            agg=spec.get('agg','mean')
            if agg not in AGGS:
                raise DataError('invalid_method')
            matrix=df.groupby(x,dropna=False,observed=True)[numeric_cols].agg(agg)
            sampled=len(matrix)>60 or len(numeric_cols)>60
            matrix=matrix.iloc[:60,:60]
            ids=[]
            for j,value in enumerate(matrix.index):
                rows=df.loc[df[x].isna() if pd.isna(value) else df[x]==value].index[:5000].tolist()
                ids.append(rows)
            values=matrix.to_numpy().astype(float)
            finite=values[np.isfinite(values)]
            bounds=[float(finite.min()),float(finite.max())] if finite.size else [0.,1.]
            if bounds[0]==bounds[1]:
                bounds[1]=bounds[0]+1
            return {'type':typ,'xLabels':matrix.columns.tolist(),'yLabels':[str(v) for v in matrix.index],'cells':clean([[i,j,matrix.iloc[j,i]] for j in range(len(matrix)) for i in range(len(matrix.columns))]),'rowIds':ids,'range':bounds,'palette':palette,'sampled':sampled}
        if method not in {"pearson", "spearman", "kendall"}:
            raise DataError("invalid_method")
        matrix = df[numeric_cols].corr(method=method)
        return {"type": typ, "labels": numeric_cols, "cells": clean([[i, j, matrix.iloc[j, i]] for i in range(len(matrix)) for j in range(len(matrix))]), "palette": palette, "sampled": False}
    if typ not in {"bar", "line", "area", "pie"}:
        raise DataError("invalid_method")
    agg = spec.get("agg", "mean")
    if agg not in AGGS:
        raise DataError("invalid_method")
    if y:
        check_columns(df, [y])
        if agg in {"mean", "sum", "median", "std"}:
            numeric(df, y)
    if color:
        check_columns(df, [color])
        if color == x:
            color = None
    groups = list(df.groupby(color, dropna=False, observed=True))[:12] if color else [(y or "count", df)]
    data = []
    # Limit displayed categories; aggregates are calculated on the complete selected dataset.
    labels = df[x].drop_duplicates().sort_values(key=lambda s: s.astype(str)).head(60).tolist()
    if spec.get("sort") == "descending":
        metric = df.groupby(x, dropna=False, observed=True)[y].agg(agg) if y else df.groupby(x, dropna=False, observed=True).size()
        labels = metric.sort_values(ascending=False).head(60).index.tolist()
    for label, frame in groups:
        values = frame.groupby(x, dropna=False, observed=True)[y].agg(agg) if y else frame.groupby(x, dropna=False, observed=True).size()
        pairs = []
        for value in labels:
            subset = frame.loc[frame[x].isna() if pd.isna(value) else frame[x] == value]
            metric = values.loc[value] if not pd.isna(value) and value in values.index else (values.loc[values.index.isna()].iloc[0] if pd.isna(value) and values.index.isna().any() else 0)
            pairs.append({"name": str(value), "value": clean(metric), "ids": subset.index[:5000].tolist()})
        data.append({"name": str(label), "data": pairs})
    return {"type": typ, "labels": [str(v) for v in labels], "series": clean(data), "palette": palette, "sampled": df[x].nunique(dropna=False)>60 or bool(color and df[color].nunique(dropna=False)>12)}


def analyze(df, p):
    selected = p.get("selection")
    if selected is not None:
        df = df.loc[df.index.isin(selected)]
    mode = p.get("kind", "describe")
    if mode == "describe":
        return {"rows": describe(df), "count": len(df)}
    if mode == "chart":
        return chart(df, p["spec"])
    if mode == 'timeline':
        from .timeseries import timeline
        return timeline(df,p['spec'])
    if mode == "select":
        if p.get('group') and p.get('categories'):
            check_columns(df,[p['group']])
            df=df.loc[df[p['group']].astype(str).isin(p['categories'])]
        c = p['field']
        check_columns(df,[c])
        low, high = float(p['lower']), float(p['upper'])
        if kind(df[c])=='date' or p.get('temporal'):
            if kind(df[c])!='date':
                from .extensions import dates
                df=df.copy();df[c]=dates(df[c],{'timezone':'utc'})
            low=pd.to_datetime(low,unit='ms',utc=True);high=pd.to_datetime(high,unit='ms',utc=True)
            if df[c].dt.tz is None:
                low=low.tz_localize(None);high=high.tz_localize(None)
        else:
            numeric(df,c)
        mask = (df[c] >= low) & (df[c] <= high if p.get('includeUpper') else df[c] < high)
        return {'ids': df.index[mask][:5000].tolist(), 'total': int(mask.sum())}
    if mode == "missing":
        sample = df.head(150)
        return {"labels": list(df.columns), "cells": [[c, r, int(pd.isna(v))] for r, row in enumerate(sample.itertuples(index=False, name=None)) for c, v in enumerate(row)], "rows": len(sample), "total": len(df)}
    if mode == "outliers":
        c = p["field"]
        numeric(df, c)
        mask, low, high = outlier_mask(df[c], p.get("method", "iqr"), {**p, "bounds": True})
        return clean({"count": int(mask.sum()), "lower": low, "upper": high, "table": table(df.loc[mask]), "ids": df.index[mask][:5000].tolist()})
    if mode == "test":
        c, test = p["field"], p["test"]
        check_columns(df, [c])
        if test == "normality":
            numeric(df, c)
            s = df[c].dropna()
            if len(s) < 3 or s.nunique() < 2:
                raise DataError("insufficient_data")
            s = s.head(5000)
            value, prob = stats.shapiro(s)
            return clean({"statistic": value, "p": prob, "n": len(s), "test": test})
        group = p["group"]
        check_columns(df, [group])
        if test == "ttest":
            numeric(df, c)
            cats = p.get("categories") or df[group].dropna().unique().tolist()[:2]
            if len(cats) != 2:
                raise DataError("two_groups_required")
            samples = [df.loc[df[group].astype(str) == str(cat), c].dropna() for cat in cats]
            if min(map(len, samples)) < 2:
                raise DataError("insufficient_data")
            value, prob = stats.ttest_ind(*samples, equal_var=False)
            return clean({"statistic": value, "p": prob, "n": list(map(len, samples)), "categories": clean(cats), "test": test})
        if test == "chi2":
            contingency = pd.crosstab(df[c], df[group])
            if min(contingency.shape) < 2:
                raise DataError("insufficient_data")
            if contingency.size > 10000:
                raise DataError("result_too_large")
            value, prob, dof, expected = stats.chi2_contingency(contingency)
            return clean({"statistic": value, "p": prob, "dof": dof, "expectedBelow5": int((expected < 5).sum()), "test": test})
        raise DataError("invalid_method")
    raise DataError("invalid_operation")

-- Émissions agrégées au grain (date_key x région x scope) pour la page ESG.
select
    e.date_key,
    -- Même résidu que dans fact_kpis_mensuels : UWI absents de dim_puits (hors AER ST37).
    coalesce(w.region, 'Puits hors référentiel AER') as region,
    e.scope,
    sum(e.co2_tonnes)  as co2_tonnes,
    sum(e.ch4_tonnes)  as ch4_tonnes,
    sum(e.co2eq_total) as co2eq_total
from {{ ref('stg_emissions') }} e
left join {{ ref('dim_puits') }} w using (uwi)
group by 1, 2, 3

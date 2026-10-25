{#
    Par défaut, dbt préfixe un schéma personnalisé par le schéma de la target :
    +schema: alberta_silver deviendrait alberta_gold_alberta_silver.
    Ici, le nom déclaré dans dbt_project.yml est pris tel quel ; la target ne sert
    que pour un modèle sans +schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}

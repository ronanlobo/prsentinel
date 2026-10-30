# BugsInPy scan for PRSentinel\n\nTotal bugs found: 501\n\nAfter R1: 44\n\n## R1 per project\n- thefuck: 14\n- youtube-dl: 10\n- pandas: 5\n- keras: 4\n- scrapy: 3\n- black: 2\n- ansible: 1\n- cookiecutter: 1\n- fastapi: 1\n- PySnooper: 1\n- tornado: 1\n- tqdm: 1\n\n## R3 blocking\n- keras: 4\n- matplotlib: 7\n- numpy: 11\n- pandas: 9\n- scipy: 11\n- tensorflow: 4\n\nAfter R1+R3: 33\n\n## Survivors\n- ansible/4 func=_ensure_default_collection py="3.6.9" file=lib/ansible/playbook/collectionsearch.py\n- black/17 func=lib2to3_parse py="3.8.3" file=black.py\n- black/9 func=lib2to3_parse py="3.8.3" file=black.py\n- cookiecutter/2 func=run_script py="3.6.9" file=cookiecutter/hooks.py\n- fastapi/3 func=_prepare_response_content py="3.8.3" file=fastapi/routing.py\n- PySnooper/2 func=get_local_reprs py="3.8.1" file=pysnooper/tracer.py\n- scrapy/14 func=is_gzipped py="3.8.3" file=scrapy/utils/gz.py\n- scrapy/15 func=_safe_ParseResult py="3.8.3" file=scrapy/utils/url.py\n- scrapy/7 func=_get_form_url py="3.8.3" file=scrapy/http/request/form.py\n- thefuck/1 func=get_new_command py="3.7.0" file=thefuck/rules/pip_unknown_command.py\n- thefuck/11 func=get_new_command py="3.7.0" file=thefuck/rules/git_push.py\n- thefuck/12 func=match py="3.7.0" file=thefuck/rules/no_command.py\n- thefuck/13 func=match py="3.7.0" file=thefuck/rules/git_branch_exists.py\n- thefuck/18 func=match py="3.7.0" file=thefuck/rules/sudo.py\n- thefuck/19 func=get_new_command py="3.7.0" file=thefuck/rules/git_push_force.py\n- thefuck/21 func=match py="3.7.0" file=thefuck/rules/git_fix_stash.py\n- thefuck/25 func=get_new_command py="3.7.0" file=thefuck/rules/mkdir_p.py\n- thefuck/26 func=get_new_command py="3.7.0" file=thefuck/rules/vagrant_up.py\n- thefuck/27 func=get_new_command py="3.7.0" file=thefuck/rules/open.py\n- thefuck/28 func=get_new_command py="3.7.0" file=thefuck/rules/fix_file.py\n- thefuck/31 func=get_new_command py="3.7.0" file=thefuck/rules/git_diff_staged.py\n- thefuck/4 func=_get_aliases py="3.7.0" file=thefuck/shells/fish.py\n- thefuck/8 func=_parse_operations py="3.7.0" file=thefuck/rules/dnf_no_such_command.py\n- tornado/12 func=_oauth_signature py="3.7.0" file=tornado/auth.py\n- tqdm/1 func=_tzip py="3.6.9" file=tqdm/contrib/__init__.py\n- youtube-dl/11 func=str_to_int py="3.7.4" file=youtube_dl/utils.py\n- youtube-dl/17 func=cli_bool_option py="3.7.4" file=youtube_dl/utils.py\n- youtube-dl/21 func=urljoin py="3.7.4" file=youtube_dl/utils.py\n- youtube-dl/3 func=get_subprocess_encoding py="3.7.0" file=youtube_dl/utils.py\n- youtube-dl/37 func=uppercase_escape py="3.7.4" file=youtube_dl/utils.py\n- youtube-dl/43 func=url_basename py="3.7.4" file=youtube_dl/utils.py\n- youtube-dl/5 func=determine_ext py="3.7.0" file=youtube_dl/utils.py\n- youtube-dl/6 func=parse_dfxp_time_expr py="3.7.0" file=youtube_dl/utils.py\n\n## Excluded\nExcluded: 468 usable: 33\n\nR2 and R4: not checkable from metadata alone (bug.info/bug_patch.txt/requirements.txt do not provide full helper decomposition or guarantee witness construction without applying patches/checking project setup).\n
## Stage 1 (R2/R3 details) - appended
Order by project name then bug id. Skipped copyleft (ansible). R4 gate = reproduce on Python 3.13 using project's own bug test/witness or constructed witness, no workarounds.

Survivors from R1+R3 (33):
1. black/17 (lib2to3_parse) helpers/req/lic TBD by full clone
2. black/9 (lib2to3_parse)
3. cookiecutter/2 (run_script)
4. fastapi/3 (_prepare_response_content)
5. PySnooper/2 (get_local_reprs)
6. scrapy/14 (is_gzipped),15 (_safe_ParseResult),7 (_get_form_url)
7. thefuck/* (14 bugs)
8. tornado/12 (_oauth_signature)
9. tqdm/1 (_tzip)
10. youtube-dl/* (8 bugs)
11. ansible/4 - SKIPPED (copyleft)

R2 requires full transitive analysis on fixed files; R4 needs witness. Third-party deps filtered by R3.


### youtube-dl
| bug id | function | helper count | helper names | third-party packages | licence | verdict |
|---|---|---|---|---|---|---|
| 11 | str_to_int | 1 | ['int_or_none'] | [] (stdlib only in file) | public-domain/unlicense | passes R2 |
| 17 | cli_bool_option | 0 | [] | [] | public-domain/unlicense | passes R2 |
| 21 | urljoin | 2 | ['_decode_compat_str', 'partial_application'] | [] | public-domain/unlicense | passes R2 |
| 3 | get_subprocess_encoding | 1 | ['preferredencoding'] | [] | public-domain/unlicense | passes R2 |
| 37 | uppercase_escape | 0 | [] | [] | public-domain/unlicense | passes R2 |
| 43 | url_basename | 0 | [] | [] | public-domain/unlicense | passes R2 |
| 5 | determine_ext | 1 | ['partial_application'] | [] | public-domain/unlicense | passes R2 |
| 6 | parse_dfxp_time_expr | 0 | [] | [] | public-domain/unlicense | passes R2 |


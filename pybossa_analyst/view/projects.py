# -*- coding: utf8 -*-
"""View module for pybossa-analyst."""

import pbclient
from redis import Redis
from rq import Queue
from flask import Blueprint
from flask import render_template, request, abort, flash, redirect, url_for
from flask import current_app, session
from pybossa_analyst import analysis, forms, object_loader, auth
from pybossa_analyst.login import login_required


blueprint = Blueprint('projects', __name__)

queue = Queue('pybossa_analyst', connection=Redis())
MINUTE = 60


def _configure_pbclient():
    """Configure PyBossa client."""
    pbclient.set('api_key', session['api_key'])
    pbclient.set('endpoint', current_app.config['ENDPOINT'])


@blueprint.route('/')
@login_required
def index():
    """Projects view."""
    _configure_pbclient()
    projects = object_loader.load(pbclient.find_project)
    if not projects:  # pragma: no cover
        abort(404)

    return render_template('index.html', projects=projects)


@blueprint.route('/<short_name>')
@login_required
def analyse(short_name):
    """View for analysing the next empty result."""
    _configure_pbclient()
    projects = pbclient.find_project(short_name=short_name, limit=1, all=1)
    if not projects:  # pragma: no cover
        abort(404)

    project = projects[0]
    results = pbclient.find_results(project.id, limit=1, all=1,
                                    info='Unverified')
    if not results:  # pragma: no cover
        flash('There are no unverified results to process for this project!',
              'success')
        return redirect(url_for('.index'))

    result = results[0]
    return redirect(url_for('.analyse_result', short_name=short_name,
                            result_id=result.id))


@blueprint.route('/<short_name>/<result_id>', methods=['GET', 'POST'])
@login_required
def analyse_result(short_name, result_id):
    """View for analysing a result."""
    _configure_pbclient()
    projects = pbclient.find_project(short_name=short_name, limit=1, all=1)
    if not projects:  # pragma: no cover
        abort(404)

    project = projects[0]
    results = pbclient.find_results(project.id, id=result_id, limit=1, all=1)
    if not results:  # pragma: no cover
        abort(404)

    result = results[0]
    task = pbclient.find_tasks(project.id, id=result.task_id, all=1)[0]
    taskruns = pbclient.find_taskruns(project.id, task_id=task.id, all=1)
    auth.ensure_authorized_to_update(short_name)

    if request.method == 'POST':
        data = request.form.to_dict()
        data.pop('csrf_token', None)
        result.info = data
        resp = pbclient.update_result(result)
        error = isinstance(resp, dict) and resp.get('exception_msg')
        if error:  # pragma: no cover
            err_msg = '{0}: {1}'.format(resp['exception_cls'],
                                        resp['exception_msg'])
            flash(err_msg, 'danger')
        return redirect(url_for('.analyse', short_name=short_name))

    excluded_keys = current_app.config['EXCLUDED_KEYS']
    keys = set(k for tr in taskruns for k in tr.info.keys()
               if k not in excluded_keys)
    return render_template('analyse.html', project=project, result=result,
                           task=task, task_runs=taskruns,
                           title=project.name, keys=keys)


@blueprint.route('/<short_name>/setup', methods=['GET', 'POST'])
@login_required
def setup(short_name):
    """View for setting up results analysis."""
    _configure_pbclient()
    projects = pbclient.find_project(short_name=short_name, limit=1, all=1)
    if not projects:  # pragma: no cover
        abort(404)

    project = projects[0]
    auth.ensure_authorized_to_update(short_name)

    form = forms.SetupForm(request.form)
    if request.method == 'POST' and form.validate():
        info_filter = form.info_filter.data
        kwargs = {
            'api_key': session['api_key'],
            'endpoint': current_app.config['ENDPOINT'],
            'project_id': project.id,
            'project_short_name': project.short_name,
            'info_filter': info_filter,
            'match_percentage': current_app.config['MATCH_PERCENTAGE'],
            'excluded_keys': current_app.config['EXCLUDED_KEYS']
        }
        queue.enqueue_call(func=analysis.analyse_multiple,
                           kwargs=kwargs,
                           timeout=10*MINUTE)
        flash('"{0}" results will be reanalysed.'.format(info_filter),
              'success')
    elif request.method == 'POST':  # pragma: no cover
        flash('Please correct the errors.', 'danger')
    return render_template('setup.html', title="Setup", project=project,
                           form=form)
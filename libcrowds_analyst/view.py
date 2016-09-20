# -*- coding: utf8 -*-
"""View module for libcrowds-analyst."""

import os
import json
import time
import enki
from redis import Redis
from rq import Queue
from flask import render_template, request, abort, flash, redirect, url_for
from flask import current_app, Response, send_file, jsonify
from werkzeug.utils import secure_filename
from libcrowds_analyst import analysis, auth, forms
from libcrowds_analyst.core import zip_builder, api_client


queue = Queue('libcrowds_analyst', connection=Redis())


def index():
    """Index view."""
    if request.method == 'GET':
        return render_template('index.html', title="LibCrowds Analyst")
    else:
        project = api_client.get_project(request.json['project_short_name'])
        if not project:  # pragma: no cover
            abort(404)

        analyst_func = analysis.get_analyst_func(project.category_id)
        if analyst_func:
            queue.enqueue(analyst_func, current_app.config['API_KEY'],
                          current_app.config['ENDPOINT'],
                          request.json['project_short_name'],
                          request.json['task_id'], timeout=600)
            return "OK"
        else:
            abort(404)


def analyse_next_empty_result(short_name):
    """View for analysing the next empty result."""
    project = api_client.get_project(short_name)
    if not project:  # pragma: no cover
        abort(404)

    result = api_client.get_first_result(project.id, info='Unanalysed')
    if not result:  # pragma: no cover
        flash('There are no unanlysed results to process!', 'success')
        return redirect(url_for('.index'))
    return redirect(url_for('.analyse_result', short_name=short_name,
                            result_id=result.id))


def analyse_result(short_name, result_id):
    """View for analysing a result."""
    try:
        e = enki.Enki(current_app.config['API_KEY'],
                      current_app.config['ENDPOINT'], short_name, all=1)
    except enki.ProjectNotFound:  # pragma: no cover
        abort(404)

    result = api_client.get_first_result(e.project.id, id=result_id)
    if not result:  # pragma: no cover
        abort(404)

    if request.method == 'POST':
        data = request.form.to_dict()
        data.pop('csrf_token', None)
        result.info = data
        api_client.update_result(result)
        return redirect(url_for('.analyse_next_empty_result',
                                short_name=short_name))

    e.get_tasks(task_id=result.task_id)
    e.get_task_runs()
    task = e.tasks[0]
    task_runs = e.task_runs[task.id]
    url = 'category_{0}.html'.format(e.project.category_id)
    return render_template(url, project=e.project, result=result, task=task,
                           task_runs=task_runs, title=e.project.name)


def edit_result(short_name, result_id):
    """View for directly editing a result."""
    project = api_client.get_project(short_name)
    if not project:  # pragma: no cover
        abort(404)

    result = api_client.get_first_result(project.id, id=result_id)
    if not result:  # pragma: no cover
        abort(404)

    form = forms.EditResultForm(request.form)
    if request.method == 'POST' and form.validate():
        result.info = json.loads(form.info.data)
        api_client.update_result(result)
        flash('Result updated.', 'success')
    elif request.method == 'POST' and not form.validate():  # pragma: no cover
        flash('Please correct the errors.', 'danger')
    form.info.data = json.dumps(result.info)
    title = "Editing result {0}".format(result.id)
    return render_template('edit_result.html', form=form, title=title)


def reanalyse(short_name):
    """View for triggering reanalysis of all results."""
    try:
        e = enki.Enki(current_app.config['API_KEY'],
                      current_app.config['ENDPOINT'], short_name, all=1)
    except enki.ProjectNotFound:  # pragma: no cover
        abort(404)

    form = forms.ReanalysisForm(request.form)
    analyst_func = analysis.get_analyst_func(e.project.category_id)
    if not analyst_func:
        flash('No analyst configured for this category of project.', 'danger')
    elif request.method == 'POST' and form.validate():
        e.get_tasks()
        sleep = int(request.form.get('sleep', 2))  # To handle API rate limit
        for t in e.tasks:
            queue.enqueue(analyst_func, current_app.config['API_KEY'],
                          current_app.config['ENDPOINT'], short_name, t.id,
                          sleep=sleep, timeout=3600)
        flash('''Results for {0} completed tasks will be reanalysed.
              '''.format(len(e.tasks)), 'success')
    elif request.method == 'POST' and not form.validate():  # pragma: no cover
        flash('Please correct the errors.', 'danger')
    return render_template('reanalyse.html', title="Reanalyse results",
                           project=e.project, form=form)


def prepare_zip(short_name):
    """View to prepare a zip file for download."""
    project = api_client.get_project(short_name)
    if not project:  # pragma: no cover
        abort(404)

    form = forms.DownloadForm(request.form)
    if request.method == 'POST' and form.validate():
        importer = form.importer.data
        task_ids = form.task_ids.data.split()
        filename = '{0}_input_{1}.zip'.format(short_name, int(time.time()))
        filename = secure_filename(filename)
        queue.enqueue(zip_builder.build, short_name, task_ids, filename,
                      importer, timeout=3600)
        return redirect(url_for('.download_zip', filename=filename,
                                short_name=project.short_name))
    elif request.method == 'POST' and not form.validate():  # pragma: no cover
        flash('Please correct the errors.', 'danger')

    return render_template('prepare_zip.html', title="Download task input",
                           project=project, form=form)


def check_zip(short_name, filename):
    """Check if a zip file is ready for download."""
    download_ready = zip_builder.check_zip(filename)
    return jsonify(download_ready=download_ready)


def download_zip(short_name, filename):
    """View to download a zip file."""
    if request.method == 'POST':
        resp = zip_builder.response_zip(filename)
        if resp is not None:
            return resp
    return render_template('download_zip.html', title="Download task input",
                           short_name=short_name, filename=filename)

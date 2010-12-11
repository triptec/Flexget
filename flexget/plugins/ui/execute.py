import logging
from flask import render_template, request, Response, redirect, flash
from flask import Module, escape
from flexget.webui import register_plugin, manager, BufferQueue
from Queue import Empty
from flask.helpers import jsonify

execute = Module(__name__, url_prefix='/execute')

log = logging.getLogger('ui.execute')

bufferqueue = BufferQueue()


@execute.route('/', methods=['POST', 'GET'])
def index():
    context = {'help': manager.parser.get_help()}
    if request.method == 'POST':
        options = manager.parser.parse_args(request.form.get('options', ''))[0]
        if manager.parser.error_msg:
            flash(escape(manager.parser.error_msg), 'error')
            context['options'] = request.form['options']
        else:
            flash('Manual execution started.', 'success')
            from flexget.webui import executor
            executor.execute(options=options, output=bufferqueue)
            context['execute_progress'] = progress(as_list=True)
            
    return render_template('execute.html', **context)


@execute.route('/progress.json')
def progress(as_list=False):
    '''
    Gives takes messages from the queue and exports them to JSON.
    '''
    result = {'items': []}
    try:
        while 1:
            item = bufferqueue.get_nowait()
            item = item.rstrip('\n')
            if item:
                item
                result['items'].append(item)
            bufferqueue.task_done()
    except Empty:
        pass

    if as_list:
        return result['items']

    return jsonify(result)


register_plugin(execute, menu='Execute')

import copy
import itertools
import os
import re
import sys

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np

os.makedirs('images', exist_ok=True)

#targets = ['fake_proxy']
targets = ['sending_rate_changing', 'fake_proxy', 'batch_size_changing', 'batch_delay_test', 'batch_delay_test_focused']
#source_folder = '/home/hudi/remote-mounts/mininet/tutorials/exercises/results'
source_folder = '/home/hudi/remote-mounts/elte-switch/exercises/results'
target_folder = '/home/hudi/t4/proxy_doc/images'
for target in targets:
    x_label = 'batch_size'
    grid_x_field = None
    grid_y_field = None
    line_fields = ['target_port']
    value_field_array = ['message_per_sec_mean']
    plot_type = 'line'
    small = True
    topleft_title = None
    relabel_to_percent = False
    percent_decimals = 0
    force_figsize = None
    force_title = None
    force_xlabel_legend = None
    force_ylabel_legend = None
    merge_value_field_plots = False
    force_xticks = None
    logx = False
    logy = False


    def load_and_prepare_df(filename):
        df_original = pd.read_csv(filename)
        print(df_original.dtypes)
        #df_original.drop('ticks', axis=1, inplace=True)
        #df_original = df_original.groupby(['rate_limiter_buffer_size'], as_index=False).mean()
        #print(df_original)
        return df_original

    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_rows", None)

    if target == 'sending_rate_changing':
        df_original = load_and_prepare_df(f'{source_folder}/sending_rate_changing.csv')
        df_original['target_port'] = df_original['target_port'].map({50051: 'Without proxy', 60051: 'With proxy'})
        line_fields = ['target_port']
        x_label = 'sending_rate'
        force_title = 'Request per second arrived to the dataplane'
        force_xlabel_legend = 'Request per second sent by control plane'
    elif target == 'fake_proxy':
        df_original = load_and_prepare_df(f'{source_folder}/fake_proxy.csv')
        df_original['fake_proxy'] = df_original['fake_proxy'].map({True: 'Fake proxy', False: 'Real proxy'})
        line_fields = ['fake_proxy']
        x_label = 'sending_rate'
        force_title = 'Request per second arrived to the dataplane'
        force_xlabel_legend = 'Request per second sent by control plane'
    elif target == 'batch_size_changing':
        df_original = load_and_prepare_df(f'{source_folder}/batch_size_changing.csv')
        df_original['target_port'] = df_original['target_port'].map({50051: 'Without proxy', 60051: 'With proxy'})
        df_original = df_original[df_original['batch_size'] < 4096]
        logx = True
        force_title = 'Request per second arrived to the dataplane'
        force_xlabel_legend = 'Number of updates in one request'
    elif target == 'batch_delay_test':
        df_original = load_and_prepare_df(f'{source_folder}/batch_delay_test.csv')
        df_original['batch_delay'] = df_original['batch_delay'].fillna(0)
        x_label = 'batch_delay'
        line_fields = ['sender_num']
        logx = True
        force_title = 'Request per second arrived to the dataplane'
        force_xlabel_legend = 'Max size of a batch in seconds'
    elif target == 'batch_delay_test_focused':
        df_original = load_and_prepare_df(f'{source_folder}/batch_delay_test.csv')
        df_original['batch_delay'] = df_original['batch_delay'].fillna(0)
        df_original = df_original[df_original['batch_delay'] < 0.0033]
        x_label = 'batch_delay'
        line_fields = ['sender_num']
        force_title = 'Request per second arrived to the dataplane'
        force_xlabel_legend = 'Max size of a batch in seconds'
        logx = False

    print(df_original)
    output_filename = str(target) + '.png'

    # column | row | line
    MULTI_Y_VALUE_MODE_COLUMN = 'column'
    MULTI_Y_VALUE_MODE_ROW = 'row'
    multi_y_value_mode = MULTI_Y_VALUE_MODE_COLUMN


    style_rules = {
    }

    regexp_style_rules = {
    }

    unique_values_dict = {c: sorted(df_original[c].unique()) for c in df_original.columns}

    value_field_array_caused_size_need = 1 if merge_value_field_plots else len(value_field_array)
    col_multiplier = value_field_array_caused_size_need if multi_y_value_mode == MULTI_Y_VALUE_MODE_COLUMN else 1
    row_multiplier = value_field_array_caused_size_need if multi_y_value_mode == MULTI_Y_VALUE_MODE_ROW else 1

    if grid_x_field is None:
        col_num = 1
    else:
        col_num = len(unique_values_dict[grid_x_field]) * col_multiplier

    if grid_y_field is None:
        row_num = 1
    else:
        row_num = len(unique_values_dict[grid_y_field]) * row_multiplier

    print("Generating grid with ", row_num, " row and ", col_num, " column")
    fig, axs = plt.subplots(row_num, col_num, squeeze=False)

    def find_unique_values_from_local_dict(local_unique_values_dict):
        title_elements = []
        for c in local_unique_values_dict:
            values = local_unique_values_dict[c]
            if len(values) == 1:
                val = values[0]
                if (not isinstance(val, str) or val != "") and not isinstance(val, str) and not np.isnan(val):
                    title_elements.append(c + ":" + str(val))
        return title_elements

    def merge_dataframes_by_column(dataframes, x_label):
        ret = dataframes[0]
        for i in range(1, len(dataframes)):
            ret = pd.merge(ret, dataframes[i], on=x_label)
        return ret

    for value_iterator, value_field in enumerate(value_field_array):
        if grid_x_field is None:
            grid_x_iter = [(0, None)]
        else:
            grid_x_iter = enumerate(unique_values_dict[grid_x_field])

        if grid_y_field is None:
            grid_y_iter = [(0, None)]
        else:
            grid_y_iter = enumerate(unique_values_dict[grid_y_field])

        for x_position, grid_x_field_value in grid_x_iter:
            for y_position, grid_y_field_value in grid_y_iter:
                df = df_original
                if grid_x_field is not None:
                    df = df[df[grid_x_field] == grid_x_field_value]
                if grid_y_field is not None:
                    df = df[df[grid_y_field] == grid_y_field_value]

                local_unique_values_dict = {c: df[c].unique() for c in df.columns}
                title = "---" + str(value_field[0] if isinstance(value_field, list) else value_field) + "---\n"
                title_elements = find_unique_values_from_local_dict(local_unique_values_dict)
                title += ", ".join(title_elements)

                print("----------------------")
                print(title)

                subdfs = []
                target_labels = []
                style_ar = []  # ['r-','r--','r:','y-','y--','y:','g-','g--','g:','b-','b--','b:']

                line_fields_values = [unique_values_dict[x] for x in line_fields]
                final_line_fields = line_fields[:]
                if isinstance(value_field, list):
                    line_fields_values.append(value_field)
                    final_line_fields += [value_field]

                line_field_conditions_array = list(itertools.product(*line_fields_values))

                for line_field_conditions in line_field_conditions_array:
                    print("-------", final_line_fields, line_field_conditions)

                    target_label = "_".join([str(x) for x in line_field_conditions])
                    if merge_value_field_plots:
                        target_label += f' ({value_field})'
                    print("TARGET LABEL", target_label)
                    target_labels.append(target_label)

                    final_value_field = copy.deepcopy(value_field)
                    df_local = df
                    for i in range(len(final_line_fields)):
                        if isinstance(final_line_fields[i], list):
                            final_value_field = line_field_conditions[i]
                        else:
                            df_local = df_local[df_local[final_line_fields[i]] == line_field_conditions[i]]

                    df_local = df_local[[x_label, final_value_field]]
                    df_local = df_local.rename(columns={final_value_field: target_label})

                    subdfs.append(df_local)

                    print("----------- STYLING")
                    style_result = ""
                    for i, field in enumerate(final_line_fields):
                        if not isinstance(field, list) and field in style_rules:
                            if line_field_conditions[i] in style_rules[field]:
                                style_result += style_rules[field][line_field_conditions[i]]
                    print("Style: ", style_result)
                    style_ar.append(style_result)

                    # print(df_local)

                draw_df = merge_dataframes_by_column(subdfs, x_label)
                if merge_value_field_plots:
                    col_shift_by_value = row_shift_by_value = 0
                else:
                    col_shift_by_value = value_iterator if multi_y_value_mode == MULTI_Y_VALUE_MODE_COLUMN else 0
                    row_shift_by_value = value_iterator if multi_y_value_mode == MULTI_Y_VALUE_MODE_ROW else 0

                ax = axs[y_position * row_multiplier + row_shift_by_value][
                    x_position * col_multiplier + col_shift_by_value]
                has_legend = 1 if x_position == 0 and y_position == 0 else None
                draw_df = draw_df.sort_values(by=[x_label])
                # with pd.option_context('display.max_rows', None, 'display.max_columns', None):
                print(draw_df)

                if len(draw_df.index):
                    # mean_df = draw_df.groupby(x_label, as_index=False).max()
                    # std_df = draw_df.groupby(x_label, as_index=False).std()
                    print(draw_df)
                    if force_figsize is not None:
                        fig_x_size = force_figsize[0] * col_num
                        fig_y_size = force_figsize[1] * row_num
                    else:
                        fig_x_size = (6 if small else 16) * col_num
                        fig_y_size = (3.5 if small else 7) * row_num
                    final_title = force_title if force_title is not None else title

                    if plot_type == 'bar':
                        ax = draw_df.plot.bar(x=x_label, ax=ax, legend=has_legend, figsize=(fig_x_size, fig_y_size),
                                              title=final_title, rot=0)
                    else:
                        ax = draw_df.plot(x=x_label, logx=logx, logy=logy, y=target_labels, style=style_ar, marker='o', ax=ax,
                                          legend=has_legend, figsize=(fig_x_size, fig_y_size),
                                          title=final_title)

                    if force_xlabel_legend is not None:
                        ax.set_xlabel(force_xlabel_legend)

                    if force_ylabel_legend is not None:
                        ax.set_ylabel(force_ylabel_legend)

                    if topleft_title is not None:
                        ax.ticklabel_format(style='plain', axis='y')
                        ax.text(0,1.035,topleft_title, transform=ax.transAxes)

                    if force_xticks is not None:
                        ax.set_xticks(force_xticks)
    plt.subplots_adjust(bottom=0.15)
    plt.savefig(f'{target_folder}/{output_filename}', dpi=300)

    plt.show()

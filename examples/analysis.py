import numpy as np
# from scipy.optimize import curve_fit
import time
import typing
from datetime import datetime
import os
# import paho.mqtt.client as mqtt
import json





class _AnalysisStruct:
    def __init__(self, n, tag, name):
        self._fluorescence_list = []
        self._fluorescence_list2 = []
        self._fluorescence_total = []
        self._mag_list = []
        self._temp_array1 = np.zeros(n)
        self._temp_array2 = np.zeros(n)
        self._spectrum = np.zeros(n)
        self._fluorescence_dataset_name = "fluorescence_"+tag
        self._fluorescence_dataset_name2 = "fluorescence2_"+tag
        self._fluorescence_dataset_total_name = "fluorescence_total_"+tag
        self._mag_dataset_name = "mag_"+tag
        self._major_dataset_name = name+"_"+tag
        self._array1_name = "array1_"+tag
        self._array2_name = "array2_"+tag
        self._loading_rate_name = 'loading rate_'+tag
        self._recapture_rate_name = 'recapture rate_'+tag
        
        self._a = 0
        self._b = 0
        self._total = 0
        self._loading_rate = 0.0
        self._recapture_rate = 0.0


class _AnalysisStruct2D:
    def __init__(self, n1, n2, tag, name):
        self._fluorescence_list = []
        self._fluorescence_list2 = []
        self._fluorescence_total = []
        self._mag_list = []
        self._temp_array1 = np.zeros(n1*n2)
        self._temp_array2 = np.zeros(n1*n2)
        self._spectrum = np.zeros(n1*n2)
        self._spectrum2 = np.zeros(n1*n2)
        self._count_1 = np.zeros(n1*n2)
        self._data = self._spectrum.reshape(n1,n2)
        self._data2 = self._spectrum.reshape(n1,n2)
        self._fluorescence_dataset_name = "fluorescence_"+tag
        self._fluorescence_dataset_name2 = "fluorescence2_"+tag
        self._fluorescence_dataset_total_name = "fluorescence_total_"+tag
        self._mag_dataset_name = "mag_"+tag
        self._major_dataset_name = name+"_"+tag
        self._array1_name = "array1_"+tag
        self._array2_name = "array2_"+tag
        self._loading_rate_name = 'loading rate_'+tag
        self._recapture_rate_name = 'recapture rate_'+tag
        self._n1 = n1
        self._n2 = n2
        
        self._a = 0
        self._b = 0
        self._total = 0
        self._loading_rate = 0.0
        self._recapture_rate = 0.0

    def update_data(self):
        self._data = self._spectrum.reshape(self._n1,self._n2)
        self._data2 = self._spectrum2.reshape(self._n1,self._n2)


class _AnalysisStructBase:
    kernel_invariants: typing.Set[str]
    def __init__(self):
        super(_AnalysisStructBase, self).__setattr__('kernel_invariants', set())

    def __repr__(self)->str:
        attributes: str = ', '.join(f'{k}={getattr(self, k)}' for k in self.kernel_invariants)
        return f'{self.__class__.__name__}: {attributes}'

    def __setattr__(self, key, value):
        super(_AnalysisStructBase, self).__setattr__(key, value)
        self.kernel_invariants.add(key)


from sipyco.pc_rpc import Client
import numpy as np
import h5py
from collections import defaultdict


class AnalisisModule:
    def __init__(self):
        self.qcmos = Client("192.168.50.47", 13250, "qcmos")
        self.dznb_n = 0
        self.rois = []
        self.dznb = 0
        self.dznb_n = 0
        self.dzztmnb = 0
        # 初始化数据集字典
        self.dataset = defaultdict(lambda: None)

        self.data = _AnalysisStructBase()
        self.rid_counter = self._load_rid_counter()  # 从文件加载RID计数器

        # 在AnalisisModule类的__init__方法中添加：
        # self.mqtt_client = mqtt.Client()
        # self.mqtt_client.connect("localhost", 1883, 60)  # 根据实际情况修改MQTT代理地址
        # self.mqtt_client.loop_start()
        
    def _load_rid_counter(self, counter_file="results/rid_counter.json"):
        """
        从文件中加载RID计数器
        Args:
            counter_file: 计数器文件路径
        Returns:
            int: 当前的RID计数器值
        """
        try:
            os.makedirs(os.path.dirname(counter_file), exist_ok=True)
            if os.path.exists(counter_file):
                with open(counter_file, 'r') as f:
                    data = json.load(f)
                    return data.get('rid_counter', 0)
        except Exception as e:
            print(f"加载RID计数器失败: {e}")
        return 0  # 默认从0开始
    
    def _save_rid_counter(self, counter_file="results/rid_counter.json"):
        """
        保存RID计数器到文件
        Args:
            counter_file: 计数器文件路径
        """
        try:
            os.makedirs(os.path.dirname(counter_file), exist_ok=True)
            with open(counter_file, 'w') as f:
                json.dump({'rid_counter': self.rid_counter}, f)
        except Exception as e:
            print(f"保存RID计数器失败: {e}")

    def basic_init(self, threshold, rois, rois_len):
        self.data.threshold = threshold
        self.data.stop_timestamp = 0
        self.data.rois = rois
        self.data.rois_len = rois_len

        self.stop_timestamp_name = 'stop_time'

        self.first_fluorescence_name = 'fluorescence/first'
        self.last_fluorescence_name = 'fluorescence/last'

        self.data.fluo_1 = []
        self.data.fluo_2 = []

        self.loading_rate_name = 'basic/loading_rate'
        self.recapture_rate_name  = 'basic/recapture_rate'
        self.data.n_1 = np.zeros(self.data.rois_len)
        self.data.n_2 = np.zeros(self.data.rois_len)
        self.data.n_total = np.zeros(self.data.rois_len)
        self.data.loading_rate = np.zeros(self.data.rois_len)
        self.data.recapture_rate = np.zeros(self.data.rois_len)
        self.set_dataset('basic/rois', np.array(rois))

    def spectrum_init(self, n, tag):
        self.data.n = n
        self.tag = tag

        self.data.first_array = np.zeros((self.data.rois_len, n))
        self.data.second_array = np.zeros((self.data.rois_len, n))
        self.data.spectrum = np.zeros((self.data.rois_len, n))
        self.data.first_array_total = np.zeros(n)
        self.data.second_array_total = np.zeros(n)
        self.data.spectrum_total = np.zeros(n)

        self.array1_name = f'spectrum/{tag}_array1'
        self.array2_name = f'spectrum/{tag}_array2'
        self.spectrum_name = f'spectrum/{tag}_spectrum'
        self.array1_total_name = f'spectrum/{tag}_array1_total'
        self.array2_total_name = f'spectrum/{tag}_array2_total'
        self.spectrum_total_name = f'spectrum/{tag}_spectrum_total'
        
    def set_dataset(self, key, value, broadcast=False):
        """
        设置数据集中的键值对
        Args:
            key: 数据键名
            value: 数据值
            broadcast: 广播标志（在此实现中未使用）
        """
        self.dataset[key] = value
        # 如果设置了广播标志，通过MQTT发布更新
        # if broadcast:
        #     try:
        #         # 发布数据更新消息
        #         payload = {
        #             'data_type': key,
        #             'data': value.tolist() if hasattr(value, 'tolist') else value,
        #             'timestamp': time.time()
        #         }
        #         self.mqtt_client.publish("analysis/update", json.dumps(payload))
        #     except Exception as e:
        #         print(f"MQTT publish failed: {e}")
        
    def append_to_dataset(self, key, value):
        """
        向数据集中的特定键追加数据
        Args:
            key: 数据键名
            value: 要追加的数据值
        """
        if key not in self.dataset:
            self.dataset[key] = []
        
        if isinstance(self.dataset[key], list):
            self.dataset[key].append(value)
        else:
            # 如果当前值不是列表，则转换为列表后再追加
            current_value = self.dataset[key]
            self.dataset[key] = [current_value, value]

    def _mutate_dataset(self, key, index, value):
        """
        Mutate an existing dataset at the given index (e.g. set a value at
        a given position in a NumPy array)

        If the dataset was created in broadcast mode, the modification is
        immediately transmitted.

        If the index is a tuple of integers, it is interpreted as
        ``slice(*index)``.
        If the index is a tuple of tuples, each sub-tuple is interpreted
        as ``slice(*sub_tuple)`` (multi-dimensional slicing).
        """
        # 获取数据集
        if key not in self.dataset:
            raise KeyError(f"Dataset '{key}' does not exist")
        
        data = self.dataset[key]
        
        # 处理索引
        if isinstance(index, tuple):
            if all(isinstance(item, tuple) for item in index):
                # 多维切片：每个子元组转换为切片
                slices = tuple(slice(*sub_index) for sub_index in index)
            else:
                # 一维切片：将元组转换为切片
                slices = slice(*index)
        else:
            # 单个索引值
            slices = index
        
        # 修改数据集
        if isinstance(data, np.ndarray):
            data[slices] = value
        elif isinstance(data, list):
            # 对于列表，我们需要特殊处理，因为列表不支持多维索引
            if isinstance(slices, int):
                data[slices] = value
            else:
                # 对于切片，我们需要处理可能的情况
                if isinstance(slices, slice):
                    # 计算切片对应的索引范围
                    start, stop, step = slices.indices(len(data))
                    indices = range(start, stop, step)
                    if hasattr(value, '__len__') and len(value) == len(indices):
                        for i, idx in enumerate(indices):
                            data[idx] = value[i]
                    else:
                        for idx in indices:
                            data[idx] = value
                else:
                    raise ValueError("Unsupported index type for list")
        else:
            # 对于其他数据类型，直接赋值
            self.dataset[key] = value
            
    def save_all(self, base_path="results"):
        """
        将dataset中的内容保存到H5文件中，路径格式为: base_path/YYYY-MM-DD/HH/RID.h5
        其中RID是自增的6位数字，计数器值保存在文件中
        
        Args:
            base_path: 基础路径，默认为"results"
        Returns:
            str: 保存的文件完整路径
        """
        # 获取当前日期和时间
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        hour_str = now.strftime("%H")
        
        # 自增RID
        self.rid_counter += 1
        
        # 创建完整的目录路径
        dir_path = os.path.join(base_path, date_str, hour_str)
        os.makedirs(dir_path, exist_ok=True)
        
        # 创建文件名（6位RID）
        filename = f"{self.rid_counter:06d}.h5"
        full_path = os.path.join(dir_path, filename)
        
        # 保存数据
        with h5py.File(full_path, 'w') as h5f:
            # 创建dataset组
            dataset_group = h5f.create_group("datasets")
            
            for key, value in self.dataset.items():
                # 处理嵌套的字典结构（如果有）
                if isinstance(value, dict):
                    group = dataset_group.create_group(key)
                    for sub_key, sub_value in value.items():
                        self._save_data(group, sub_key, sub_value)
                else:
                    self._save_data(dataset_group, key, value)
        
        # 保存RID计数器到文件
        self._save_rid_counter()
                    
        print(f"数据已保存到: {full_path}")
        return full_path

    def _save_data(self, h5_obj, key, data):
        """
        辅助方法：将数据保存到H5对象中
        Args:
            h5_obj: H5文件或组对象
            key: 数据键名
            data: 要保存的数据
        """
        try:
            # 尝试将数据转换为numpy数组
            if isinstance(data, list):
                data = np.array(data)
                
            if isinstance(data, np.ndarray):
                h5_obj.create_dataset(key, data=data)
            else:
                # 对于标量数据
                h5_obj.create_dataset(key, data=np.array([data]))
        except Exception as e:
            print(f"保存数据到H5文件时出错（键：{key}）: {str(e)}")
            # 如果无法处理的数据类型，将其转换为字符串保存
            h5_obj.create_dataset(key, data=str(data))

    def _process(self, data1, data2):
        results1 = np.zeros(self.data.rois_len)
        results2 = np.zeros(self.data.rois_len)
        if type(self.data.rois) is not list:
            for i, (x1, y1, x2, y2) in enumerate(self.data.rois):
                results1[i] = data1[x1:x2, y1:y2].sum()
                results2[i] = data2[x1:x2, y1:y2].sum()
        else:
            for i, (x1, y1, x2, y2) in enumerate(self.data.rois[0]):
                results1[i] = data1[x1:x2, y1:y2].sum()
            for i, (x1, y1, x2, y2) in enumerate(self.data.rois[1]):
                results2[i] = data2[x1:x2, y1:y2].sum()

        self._append_to_fluorescence(results1, results2)
        n0 = results1>self.data.threshold
        n1 = results2>self.data.threshold
        self._update_basic(n0, n1)

    def _append_to_fluorescence(self, data1, data2):
        print(data1)
        print(data2)
        self.append_to_dataset(self.first_fluorescence_name, data1)
        self.append_to_dataset(self.last_fluorescence_name, data2)
    
    def _update_basic(self, n0, n1):
        self.data.n_total += 1
        self.data.n_1[n0] += 1
        self.data.n_2[n0 & n1] += 1
        print(f"Average Recapture Rate: {np.divide(self.data.n_2.sum(), self.data.n_1.sum(), where=~np.isclose(self.data.n_1, 0,atol=1e-3))}")
        print(f"{np.divide(self.data.n_2, self.data.n_1, where=~np.isclose(self.data.n_1, 0,atol=1e-3))}")
        print(f"{self.data.n_2}/{self.data.n_1}")
        print(f"Average Loading Rate: {self.data.n_1/self.data.n_total}")
        self.set_dataset(self.recapture_rate_name, np.divide(self.data.n_2, self.data.n_1, where=~np.isclose(self.data.n_1, 0,atol=1e-3)))
        self.set_dataset(self.loading_rate_name, np.divide(self.data.n_1, self.data.n_total, where=~np.isclose(self.data.n_total, 0,atol=1e-3)), broadcast=True)
    
    def _spectrum_process(self, data1, data2, index):
        results1 = np.zeros(self.data.rois_len)
        results2 = np.zeros(self.data.rois_len)
        if type(self.data.rois) is not list:
            for i, (x1, y1, x2, y2) in enumerate(self.data.rois):
                results1[i] = data1[x1:x2, y1:y2].sum()
                results2[i] = data2[x1:x2, y1:y2].sum()
        else:
            for i, (x1, y1, x2, y2) in enumerate(self.data.rois[0]):
                results1[i] = data1[x1:x2, y1:y2].sum()
            for i, (x1, y1, x2, y2) in enumerate(self.data.rois[1]):
                results2[i] = data2[x1:x2, y1:y2].sum()
        n0 = results1>self.data.threshold
        n1 = results2>self.data.threshold
        self.data.first_array[:, index] += n0
        self.set_dataset(self.array1_name, self.data.first_array)
        self.data.first_array_total[index] += n0.sum()
        self.set_dataset(self.array1_total_name, self.data.first_array_total)
        self.data.second_array[:, index] += n0 & n1
        self.set_dataset(self.array2_name, self.data.second_array)
        self.data.second_array_total[index] += (n0 & n1).sum()
        self.set_dataset(self.array2_total_name, self.data.second_array_total)
        self.data.spectrum = np.divide(self.data.second_array, self.data.first_array, where=~np.isclose(self.data.first_array, 0, atol=1e-3))
        self.set_dataset(self.spectrum_name, self.data.spectrum,broadcast=True)
        self.data.spectrum_total = np.divide(self.data.second_array_total, self.data.first_array_total, where=~np.isclose(self.data.first_array_total, 0,atol=1e-3))
        self._mutate_dataset(self.spectrum_total_name, index, self.data.spectrum_total[index])

    def prepare(self,):
        self.qcmos.AllocAndAnnounceBuffers()
        self.qcmos.StartAcquisition()

    def analysis(self, index):
        data1 = self.qcmos._get_image()
        data2 = self.qcmos._get_image()
        self.dznb_n += 1
        self.dznb = self.dznb * (self.dznb_n-1)/self.dznb_n + data1 / self.dznb_n
        self.dzztmnb = self.dzztmnb*(self.dznb_n-1)/self.dznb_n + data2 / self.dznb_n

        self.set_dataset('fluorescence/average_img', self.dznb, broadcast=True)
        self.set_dataset('fluorescence/average_img2', self.dzztmnb, broadcast=True)
        self.set_dataset('fluorescence/first_img', data1, broadcast=True)
        self.set_dataset('fluorescence/second_img', data2, broadcast=True)
        rois = self.data.rois[0]
        r = []
        for roi in rois:
            r.append(self.dznb[roi[0]:roi[2],roi[1]:roi[3]])
        ri = []
        self.set_dataset('fluorescence/average_img_roi', np.array(r))
        self._process(data1, data2)
        # self._spectrum_process(data1, data2, index)
        # avg_fluo = self.data.fluo_1[-1]
        # a = np.array(avg_fluo)
        # a = a[a>self._threshold].mean()
        # self.append_to_dataset('fluorescence/avg_fluo_list', a)
    
    def end(self):
        self.qcmos.StopAcquisition()


if __name__ == '__main__':
    ana = AnalisisModule()

    rois = [[632, 1005, 641, 1014],
            [596, 1004, 605, 1013],
            [523, 1003, 532, 1012],
            [560, 1003, 569, 1012],
            [633, 969, 642, 978],
            [597, 967, 606, 976],
            [524, 966, 533, 975],
            [561, 966, 570, 975],]

    ana.basic_init(17000, [rois, rois], 8)
    ana.spectrum_init(10, '')
    ana.prepare()
    time.sleep(5)
    for i in range(10):
        print(i)
        ana.analysis(i)
        time.sleep(1.2) 
    ana.end()
    ana.save_all()


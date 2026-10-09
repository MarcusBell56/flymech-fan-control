import pywinusb.hid as hid

def list_all_devices():
    # 获取所有 HID 设备
    all_devices = hid.find_all_hid_devices()
    
    if not all_devices:
        print("没有找到任何 HID 设备！")
        return

    print("正在扫描连接的设备...\n")
    for device in all_devices:
        try:
            # 获取厂商名和产品名（有的设备可能读取不到）
            vendor_name = device.vendor_name
            product_name = device.product_name
            
            # 打印十六进制的 VID 和 PID
            print(f"设备: {vendor_name} {product_name}")
            print(f"  VID: 0x{device.vendor_id:04x}")
            print(f"  PID: 0x{device.product_id:04x}")
            print("-" * 30)
        except:
            pass

if __name__ == "__main__":
    list_all_devices()
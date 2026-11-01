import { useRef, useState } from 'react';
import { Image, Upload, Button, Popconfirm, Tag, message, Space } from 'antd';
import {
  CameraOutlined,
  DeleteOutlined,
  PlusOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';
import type { ItemPhoto } from '@/api/types';
import * as itemsApi from '@/api/items';
import { useQueryClient } from '@tanstack/react-query';

interface Props {
  itemId: number;
  photos: ItemPhoto[];
  readOnly?: boolean;
  onChanged?: () => void;
}

function photoUrl(p: ItemPhoto): string {
  if (p.url) return p.url;
  return p.file_path.startsWith('http') || p.file_path.startsWith('data:')
    ? p.file_path
    : `/uploads/${p.file_path}`;
}

/** 照片墙：上传/手机拍照直传/设主图/删除/预览大图 */
export default function ItemPhotoWall({ itemId, photos, readOnly, onChanged }: Props) {
  const [uploading, setUploading] = useState(false);
  const queryClient = useQueryClient();
  const cameraInputRef = useRef<HTMLInputElement>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['item', itemId] });
    onChanged?.();
  };

  const doUpload = async (file: File, source: 'upload' | 'camera') => {
    if (!file.type.startsWith('image/')) {
      message.error('只能上传图片文件');
      return;
    }
    setUploading(true);
    try {
      await itemsApi.uploadPhoto(itemId, file, source);
      message.success('照片已上传');
      refresh();
    } finally {
      setUploading(false);
    }
  };

  const fileList: UploadFile[] = photos.map((p) => ({
    uid: String(p.id),
    name: p.file_path,
    status: 'done',
    url: photoUrl(p),
  }));

  return (
    <div>
      <Image.PreviewGroup>
        <Space wrap size={12}>
          {photos.map((p) => (
            <div
              key={p.id}
              style={{
                position: 'relative',
                width: 104,
                border: '1px solid #E4DFD3',
                borderRadius: 8,
                padding: 4,
              }}
            >
              <Image
                src={photoUrl(p)}
                width={96}
                height={96}
                style={{ objectFit: 'cover', borderRadius: 4 }}
                alt={`物品照片 ${p.id}`}
              />
              <div style={{ textAlign: 'center', marginTop: 2 }}>
                <Space size={4}>
                  {p.is_primary ? (
                    <Tag color="gold" style={{ marginInlineEnd: 0 }}>
                      <StarFilled /> 主图
                    </Tag>
                  ) : (
                    !readOnly && (
                      <Button
                        type="text"
                        size="small"
                        icon={<StarOutlined />}
                        aria-label="设为主图"
                        onClick={async () => {
                          await itemsApi.setPrimaryPhoto(itemId, p.id);
                          message.success('已设为主图');
                          refresh();
                        }}
                      />
                    )
                  )}
                  {!readOnly && (
                    <Popconfirm
                      title="确定删除这张照片？"
                      onConfirm={async () => {
                        await itemsApi.deletePhoto(itemId, p.id);
                        message.success('已删除');
                        refresh();
                      }}
                    >
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        aria-label="删除照片"
                      />
                    </Popconfirm>
                  )}
                </Space>
              </div>
            </div>
          ))}
        </Space>
      </Image.PreviewGroup>

      {!readOnly && (
        <Space style={{ marginTop: 12 }} wrap>
          <Upload
            showUploadList={false}
            fileList={fileList}
            beforeUpload={(file) => {
              void doUpload(file as unknown as File, 'upload');
              return false;
            }}
          >
            <Button icon={<PlusOutlined />} loading={uploading} aria-label="上传照片">
              上传照片
            </Button>
          </Upload>
          {/* 手机拍照直传：原生 input capture=environment 调起系统相机（TS 安全） */}
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void doUpload(f, 'camera');
              e.target.value = '';
            }}
            aria-label="拍照上传文件选择"
          />
          <Button
            icon={<CameraOutlined />}
            loading={uploading}
            onClick={() => cameraInputRef.current?.click()}
            aria-label="拍照上传"
          >
            拍照上传
          </Button>
        </Space>
      )}
      {photos.length === 0 && readOnly && (
        <div style={{ color: '#999', marginTop: 8 }}>暂无照片</div>
      )}
    </div>
  );
}
